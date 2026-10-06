import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlparse

import paramiko

from server.guest import guest_env, hub
from server.ssh import alive, execute, load_known_hosts, output_of
from server.vnc import VNC, Channel, authenticate, password_of

PREFIX = "macos:"
BASE_VM = os.environ.get("ZOO_MACOS_BASE", "zoo-macos-base")
CPUS = int(os.environ.get("ZOO_MACOS_CPUS", "4"))
MEMORY_MB = int(os.environ.get("ZOO_MACOS_MEMORY_MB", "8192"))
USER = os.environ.get("ZOO_MACOS_USER", "admin")
HOME = f"/Users/{USER}"
ENV_FILE = f"{HOME}/.zoo/env"
MAX_VMS = 2
HOST_PATH = 'export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"; '
LOCAL = "local://"
SAFE_RULE = re.compile(r"^[A-Za-z0-9.:/_-]+$")
ROOT = os.path.dirname(os.path.dirname(__file__))
# zoo-guest for the VM, built by `make guest-darwin`; without it the VM's tools stay on SSH
GUEST_BINARY = os.environ.get("ZOO_GUEST_DARWIN_BINARY", os.path.join(ROOT, "guest", "dist", "zoo-guest-darwin-arm64"))
GUEST_LABEL = "com.zoo.guest"
GUEST_PLIST = f"{HOME}/Library/LaunchAgents/{GUEST_LABEL}.plist"

hosts: dict[str, paramiko.SSHClient] = {}
guests: dict[str, paramiko.SSHClient] = {}
urls: dict[str, str] = {}
lock = threading.Lock()


def is_vm(runtime_id: str | None) -> bool:
    return bool(runtime_id) and runtime_id.startswith(PREFIX)


def vm_name(sandbox_id: str) -> str:
    return f"zoo-{sandbox_id}"


def runtime_id(server_id: str, sandbox_id: str) -> str:
    return f"{PREFIX}{server_id}:{vm_name(sandbox_id)}"


def parse(runtime_id: str) -> tuple[str, str]:
    server_id, name = runtime_id[len(PREFIX) :].split(":", 1)
    return server_id, name


def is_local(server_id: str) -> bool:
    url(server_id)
    return urls[server_id] == LOCAL


def local_available() -> bool:
    return sys.platform == "darwin"


def local_zoovm() -> bool:
    dirs = [os.path.expanduser("~/.local/bin"), "/opt/homebrew/bin", "/usr/local/bin", os.environ.get("PATH", "")]
    return local_available() and shutil.which("zoovm", path=os.pathsep.join(dirs)) is not None


def ensure_local_server(user_id: str, db) -> None:
    from db.generated.query import CreateServerParams

    if not local_zoovm():
        return
    if any(s.docker_url == LOCAL for s in db.list_servers_by_user(created_by=user_id)):
        return
    import uuid

    db.create_server(
        CreateServerParams(
            id=str(uuid.uuid4()),
            name="This Mac",
            docker_url=LOCAL,
            bind_address="127.0.0.1",
            created_by=user_id,
            platform="macos",
            capabilities="macos",
        )
    )


def connect(server_id: str, url: str) -> paramiko.SSHClient | None:
    with lock:
        urls[server_id] = url
        if url == LOCAL:
            return None
        if alive(hosts.get(server_id)):
            return hosts[server_id]
        target = urlparse(url)
        client = paramiko.SSHClient()
        load_known_hosts(client)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(target.hostname, port=target.port or 22, username=target.username, timeout=15)
        client.get_transport().set_keepalive(30)
        hosts[server_id] = client
        return client


def url(server_id: str) -> str:
    if server_id not in urls:
        from db.connection import db_manager

        with db_manager.session() as db:
            server = db.get_server(id=server_id)
        if server is None:
            raise RuntimeError(f"server {server_id} not found")
        urls[server_id] = server.docker_url
    return urls[server_id]


def host(server_id: str) -> paramiko.SSHClient:
    return connect(server_id, url(server_id))


def forget(server_id: str):
    with lock:
        urls.pop(server_id, None)
        client = hosts.pop(server_id, None)
    if client is not None:
        client.close()


def run(server_id: str, command: str, stdin: bytes | None = None, timeout: float = 60):
    if is_local(server_id):
        try:
            done = subprocess.run(
                ["/bin/bash", "-c", HOST_PATH + command],
                input=stdin or b"",
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"command timed out after {timeout}s")
        return done.returncode, done.stdout, done.stderr
    return execute(host(server_id), HOST_PATH + command, stdin, timeout)


def open_socket(server_id: str, address: tuple[str, int]):
    if is_local(server_id):
        return socket.create_connection(address, timeout=15)
    return host(server_id).get_transport().open_channel("direct-tcpip", address, ("127.0.0.1", 0), timeout=15)


def check(server_id: str, command: str, stdin: bytes | None = None, timeout: float = 60) -> str:
    return output_of(run(server_id, command, stdin, timeout))


def probe(server_id: str, url: str) -> dict:
    try:
        if url == LOCAL:
            if not local_available():
                raise RuntimeError("local:// only works when the API runs on the Mac itself")
            urls[server_id] = url
        else:
            connect(server_id, url)
        check(server_id, "command -v zoovm")
        os_version = check(server_id, "sw_vers -productVersion").strip()
        cpus, memory = check(server_id, "sysctl -n hw.ncpu hw.memsize").split()
        running = len(running_vms(server_id))
    except Exception as e:
        forget(server_id)
        return {"online": False, "error": str(e)[:500]}
    return {
        "online": True,
        "name": "this Mac" if url == LOCAL else urlparse(url).hostname,
        "os": f"macOS {os_version}",
        "cpus": int(cpus),
        "memory_total": int(memory),
        "docker_version": None,
        "microvm": True,
        "containers_running": running,
    }


def running_vms(server_id: str) -> set[str]:
    return {r["name"] for r in json.loads(check(server_id, "zoovm list") or "[]") if r["state"] == "running"}


def start(sandbox_id: str, server, env: dict[str, str]) -> tuple[str, str]:
    """Clones the base VM on first boot, runs it headless with a VNC server, and waits for SSH in the guest."""
    server_id, name = server.id, vm_name(sandbox_id)
    connect(server_id, server.docker_url)
    if run(server_id, f"zoovm get {name}")[0] != 0 and not base_ready(server_id):
        raise RuntimeError("the base VM isn't set up yet: finish its setup under Remote Servers, then start again")
    rid = runtime_id(server_id, sandbox_id)
    if len(running_vms(server_id) - {name}) >= MAX_VMS:
        raise RuntimeError(f"this Mac already runs {MAX_VMS} macOS VMs, the most macOS allows")
    if run(server_id, f"zoovm get {name}")[0] != 0:
        check(server_id, f"zoovm clone {BASE_VM} {name} && zoovm set {name} --cpu {CPUS} --memory {MEMORY_MB}")
    if name in running_vms(server_id):
        # a retried boot adopts the VM an earlier attempt started
        url = check(server_id, f"zoovm vnc {name}").strip()
    else:
        url = boot(server_id, name)
    wait_for_guest(rid)
    write_env(rid, env)
    hub.bind(rid, sandbox_id)
    install_guest(rid, sandbox_id)
    return rid, url


def boot(server_id: str, name: str) -> str:
    check(server_id, f"zoovm stop {name}", timeout=60)
    log = f"~/.zoovm/vms/{name}/run.log"
    check(server_id, f"nohup zoovm run {name} > {log} 2>&1 < /dev/null &")
    return wait_for_vnc(server_id, name, log)


def wait_for_vnc(server_id: str, name: str, log: str, timeout: int = 60) -> str:
    started = time.monotonic()
    while time.monotonic() < started + timeout:
        code, out, _ = run(server_id, f"zoovm vnc {name}")
        if code == 0:
            return out.decode().strip()
        if time.monotonic() > started + 5 and name not in running_vms(server_id):
            raise RuntimeError(run(server_id, f"cat {log}")[1].decode(errors="replace").strip()[-500:] or "VM exited")
        time.sleep(0.5)
    raise RuntimeError("macOS VM did not start its VNC server in time")


def guest_client(rid: str) -> paramiko.SSHClient:
    client = guests.get(rid)
    if alive(client):
        return client
    server_id, name = parse(rid)
    ip = check(server_id, f"zoovm ip {name}").strip()
    tunnel = open_socket(server_id, (ip, 22))
    client = paramiko.SSHClient()
    # The guest sits on the Mac's private NAT network, reachable only from the Mac itself
    # (directly or through its SSH connection). Each clone gets fresh host keys, so there is nothing to pin.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username=USER, sock=tunnel, timeout=15, banner_timeout=15, auth_timeout=15)
    client.get_transport().set_keepalive(30)
    guests[rid] = client
    return client


def wait_for_guest(rid: str, timeout: int = 300):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            if guest(rid, "true", timeout=15)[0] == 0:
                return
        except Exception as e:
            error = e
            guests.pop(rid, None)
        time.sleep(2)
    raise RuntimeError(f"could not reach the macOS guest over SSH: {error}")


def guest(
    rid: str, script: str, stdin: bytes | None = None, timeout: float = 60, root: bool = False, ssh: bool = False
):
    """Runs a script in the VM as the guest user, through zoo-guest when it's connected and over SSH otherwise.
    Root scripts and ssh=True stay on SSH: osascript needs the Accessibility grant sshd has (see macos/README.md)."""
    command = f"cd {HOME} && {script}"
    agent = None if root or ssh else hub.for_runtime(rid)
    if agent is not None and agent.has("exec"):
        return agent.exec_run(["/bin/sh", "-c", command], stdin=stdin or b"", timeout=timeout)
    if root:
        command = f"sudo -n sh -c {shlex.quote(command)}"
    return execute(guest_client(rid), command, stdin, timeout)


def guest_check(
    rid: str, script: str, stdin: bytes | None = None, timeout: float = 60, root: bool = False, ssh: bool = False
) -> str:
    return output_of(guest(rid, script, stdin, timeout, root, ssh))


def guest_bytes(rid: str, script: str, timeout: float) -> bytes:
    code, out, err = guest(rid, script, timeout=timeout)
    if code != 0:
        raise RuntimeError(err.decode(errors="replace").strip() or f"exit code {code}")
    return out


def write_env(rid: str, env: dict[str, str]):
    lines = "".join(f"export {k}={shlex.quote(v)}\n" for k, v in env.items() if re.fullmatch(r"[A-Za-z_]\w*", k))
    guest_check(rid, f"mkdir -p {HOME}/.zoo && umask 077 && cat > {ENV_FILE}", stdin=lines.encode())


def install_guest(rid: str, sandbox_id: str, timeout: float = 15):
    """Copies zoo-guest into the VM when it changed, writes its config, and (re)starts it as a LaunchAgent in the
    auto-logged-in user's session. Every boot does this, so clones of an older base VM pick the guest up too."""
    env = guest_env(sandbox_id, remote=True)
    if not env or not os.path.exists(GUEST_BINARY):
        return
    with open(GUEST_BINARY, "rb") as f:
        binary = f.read()
    path = f"{HOME}/.zoo/bin/zoo-guest"
    installed = guest(rid, f"shasum -a 256 {path} 2>/dev/null", ssh=True)[1].split()[:1]
    if installed != [hashlib.sha256(binary).hexdigest().encode()]:
        guest_check(
            rid,
            f"mkdir -p {HOME}/.zoo/bin && cat > {path}.new && chmod 755 {path}.new && mv {path}.new {path}",
            stdin=binary,
            timeout=120,
            ssh=True,
        )
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{GUEST_LABEL}</string>
<key>ProgramArguments</key><array><string>{path}</string><string>-env</string><string>{HOME}/.zoo/guest.env</string></array>
<key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ProcessType</key><string>Interactive</string>
<key>StandardErrorPath</key><string>{HOME}/.zoo/guest.log</string>
</dict></plist>
"""
    guest_check(
        rid,
        f"umask 077 && cat > {HOME}/.zoo/guest.env && mkdir -p {HOME}/Library/LaunchAgents "
        f"&& cat > {GUEST_PLIST} <<'ZOO_PLIST'\n{plist}ZOO_PLIST\n"
        f"sudo -n launchctl bootstrap gui/$(id -u) {GUEST_PLIST} 2>/dev/null "
        f"|| sudo -n launchctl kickstart -k gui/$(id -u)/{GUEST_LABEL}",
        stdin="".join(f"{k}={v}\n" for k, v in env.items()).encode(),
        ssh=True,
    )
    deadline = time.monotonic() + timeout
    while hub.for_sandbox(sandbox_id) is None and time.monotonic() < deadline:
        time.sleep(0.25)


def stop(rid: str):
    server_id, name = parse(rid)
    # the guest may already be down or unreachable; stopping the VM below covers both
    with contextlib.suppress(Exception):
        guest(rid, "shutdown -h now", timeout=10, root=True)
    client = guests.pop(rid, None)
    if client is not None:
        client.close()
    run(server_id, f"zoovm stop {name} --timeout 45", timeout=60)


def delete(sandbox_id: str, server):
    name = vm_name(sandbox_id)
    connect(server.id, server.docker_url)
    run(server.id, f"zoovm stop {name}", timeout=60)
    check(server.id, f"zoovm delete {name}")


def is_running(rid: str) -> bool:
    server_id, name = parse(rid)
    return name in running_vms(server_id)


def vnc_channel(rid: str):
    """Connects to the VM's VNC server on 127.0.0.1 of the Mac, directly or through the host's SSH connection."""
    server_id, name = parse(rid)
    url = check(server_id, f"zoovm vnc {name}").strip()
    target = urlparse(url)
    channel = open_socket(server_id, (target.hostname, target.port))
    channel.settimeout(30)
    return channel, password_of(url)


@contextmanager
def vnc(rid: str):
    channel, password = vnc_channel(rid)
    try:
        yield VNC(channel, password)
    finally:
        channel.close()


def authenticated_channel(rid: str):
    channel, password = vnc_channel(rid)
    try:
        authenticate(Channel(channel), password)
    except Exception:
        channel.close()
        raise
    channel.settimeout(None)
    return channel


def export_dir(rid: str, path: str) -> bytes:
    parent, base = os.path.split(path.rstrip("/"))
    return guest_bytes(rid, f"tar -cf - -C {shlex.quote(parent)} {shlex.quote(base)}", timeout=600)


def import_dir(rid: str, parent: str, data: bytes):
    guest_check(rid, f"mkdir -p {shlex.quote(parent)} && tar -xf - -C {shlex.quote(parent)}", stdin=data, timeout=600)


def export_home(rid: str):
    yield guest_bytes(rid, f"tar -cf - --exclude {USER}/Library/Caches -C /Users {USER}", timeout=3600)


def import_home(rid: str, data: bytes):
    guest_check(rid, "tar -xf - -C /Users", stdin=data, timeout=3600)


def apply_network(rid: str, default_action: str, allow_dns: bool, rules: list[tuple[str, str, str]]):
    lines = [
        "set skip on lo0",
        # Zoo reaches the guest over SSH; keep state so replies pass a default-deny policy.
        "pass in quick proto tcp to any port 22 keep state",
        *guest_rule(),
        "pass out quick proto udp to any port 67 keep state",
        f"{'pass' if allow_dns else 'block return'} out quick proto {{ tcp udp }} to any port 53",
    ]
    for _, value, effect in rules:
        if not SAFE_RULE.match(value):
            raise ValueError(f"invalid network rule value {value!r}")
        lines.append(f"{'pass' if effect == 'allow' else 'block return'} out quick to {value}")
    lines.append("block return out all" if default_action == "deny" else "pass out all")
    guest_check(
        rid,
        "cat > /etc/zoo-pf.conf && pfctl -q -f /etc/zoo-pf.conf && (pfctl -q -e 2>/dev/null || true)",
        stdin=("\n".join(lines) + "\n").encode(),
        root=True,
    )


def guest_rule() -> list[str]:
    """Lets zoo-guest reach the API whatever the policy says."""
    target = urlparse(guest_env("", remote=True).get("ZOO_GUEST_URL", ""))
    if not target.hostname or not SAFE_RULE.match(target.hostname):
        return []
    port = target.port or (443 if target.scheme == "wss" else 80)
    return [f"pass out quick proto tcp to {target.hostname} port {port} keep state"]


def apply_apps(rid: str, effects: dict[str, str]):
    lines = []
    for app, effect in effects.items():
        binaries = shlex.quote(f"/Applications/{app}.app/Contents/MacOS")
        owner, mode = (f"{USER}:admin", "755") if effect == "allow" else ("root:wheel", "700")
        lines.append(f"[ -d {binaries} ] && chown -R {owner} {binaries} && chmod -R {mode} {binaries} || true")
    if lines:
        guest_check(rid, "\n".join(lines), root=True)


INSTALL_LOG = "~/.zoovm/install.log"
PUBLIC_KEYS = ["id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub"]
SETUP_SCRIPT = os.path.join(ROOT, "macos", "guest-setup.sh")


def base_id(server_id: str) -> str:
    return f"{PREFIX}{server_id}:{BASE_VM}"


def ready_marker() -> str:
    return f"~/.zoovm/vms/{BASE_VM}/zoo-ready"


def base_ready(server_id: str) -> bool:
    if run(server_id, f"test -f {ready_marker()}")[0] == 0:
        return True
    if BASE_VM not in running_vms(server_id):
        return False
    if run(server_id, f"nc -z -G 2 $(zoovm ip {BASE_VM}) 22", timeout=10)[0] != 0:
        return False
    try:
        ok = guest(base_id(server_id), "true", timeout=5)[0] == 0
    except Exception:
        guests.pop(base_id(server_id), None)
        return False
    if ok:
        run(server_id, f"touch {ready_marker()}")
    return ok


def base_status(server_id: str) -> dict:
    """State of the server's base VM: missing, installing, failed, stopped or running."""
    installing = run(server_id, f"pgrep -f '[z]oovm install {BASE_VM}'")[0] == 0
    log = run(server_id, f"tail -c 4000 {INSTALL_LOG} 2>/dev/null")[1].decode(errors="replace")
    last = re.split(r"[\r\n]+", log.strip())[-1] if log.strip() else ""
    if installing:
        found = re.findall(r"(\d+(?:\.\d+)?)%", last)
        phase = "installing macOS" if last.startswith("installing") else "downloading macOS"
        return {"state": "installing", "progress": float(found[-1]) if found else None, "message": phase}
    if run(server_id, f"zoovm get {BASE_VM}")[0] != 0:
        failed = "zoovm:" in log
        return {
            "state": "failed" if failed else "missing",
            "progress": None,
            "message": last[-300:] if failed else None,
        }
    state = "running" if BASE_VM in running_vms(server_id) else "stopped"
    return {"state": state, "progress": None, "message": None, "ready": base_ready(server_id)}


def base_install(server_id: str):
    check(server_id, f"mkdir -p ~/.zoovm && nohup zoovm install {BASE_VM} > {INSTALL_LOG} 2>&1 < /dev/null &")


def base_start(server_id: str) -> str:
    return boot(server_id, BASE_VM)


def base_stop(server_id: str):
    stop(base_id(server_id))


def public_key() -> str:
    for name in PUBLIC_KEYS:
        path = os.path.expanduser(f"~/.ssh/{name}")
        if os.path.exists(path):
            with open(path) as f:
                return f.read().strip()
    raise RuntimeError("the API has no SSH public key in ~/.ssh")


def base_setup(server_id: str):
    """Opens Terminal in the base VM and types the guest setup script, which then asks for the password."""
    with open(SETUP_SCRIPT) as f:
        # Drop the shebang: zsh would try to history-expand its "!" while it's typed.
        script = "".join(line for line in f if not line.startswith("#!"))
    command = (
        f"cat > /tmp/zoo-setup.sh <<'ZOO_SETUP'\n{script}ZOO_SETUP\nsh /tmp/zoo-setup.sh {shlex.quote(public_key())}\n"
    )
    with vnc(base_id(server_id)) as v:
        v.combo(["cmd", "space"])
        time.sleep(1)
        v.type("Terminal", 0.03)
        time.sleep(0.5)
        v.combo(["Return"])
        time.sleep(3)
        v.type(command, 0.015)
