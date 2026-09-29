import json
import os
import re
import shlex
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlparse

import paramiko

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
SAFE_RULE = re.compile(r"^[A-Za-z0-9.:/_-]+$")

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
    server_id, name = runtime_id[len(PREFIX):].split(":", 1)
    return server_id, name


def alive(client: paramiko.SSHClient | None) -> bool:
    return client is not None and client.get_transport() is not None and client.get_transport().is_active()


def connect(server_id: str, url: str) -> paramiko.SSHClient:
    with lock:
        urls[server_id] = url
        if alive(hosts.get(server_id)):
            return hosts[server_id]
        target = urlparse(url)
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(target.hostname, port=target.port or 22, username=target.username, timeout=15)
        client.get_transport().set_keepalive(30)
        hosts[server_id] = client
        return client


def host(server_id: str) -> paramiko.SSHClient:
    if server_id not in urls:
        from db.connection import db_manager

        with db_manager.session() as db:
            server = db.get_server(id=server_id)
        if server is None:
            raise RuntimeError(f"server {server_id} not found")
        urls[server_id] = server.docker_url
    return connect(server_id, urls[server_id])


def forget(server_id: str):
    with lock:
        urls.pop(server_id, None)
        client = hosts.pop(server_id, None)
    if client is not None:
        client.close()


def execute(client: paramiko.SSHClient, command: str, stdin: bytes | None, timeout: float) -> tuple[int, bytes, bytes]:
    channel = client.get_transport().open_session(timeout=15)
    try:
        channel.exec_command(command)
        if stdin is not None:
            channel.sendall(stdin)
        channel.shutdown_write()
        out, err = bytearray(), bytearray()
        deadline = time.monotonic() + timeout
        while True:
            if channel.recv_ready():
                out += channel.recv(65536)
            elif channel.recv_stderr_ready():
                err += channel.recv_stderr(65536)
            elif channel.exit_status_ready() and channel.eof_received:
                break
            elif time.monotonic() > deadline:
                raise TimeoutError(f"command timed out after {timeout}s")
            else:
                time.sleep(0.01)
        return channel.recv_exit_status(), bytes(out), bytes(err)
    finally:
        channel.close()


def output_of(result: tuple[int, bytes, bytes]) -> str:
    code, out, err = result
    if code != 0:
        raise RuntimeError((err or out).decode(errors="replace").strip() or f"exit code {code}")
    return out.decode(errors="replace")


def run(server_id: str, command: str, stdin: bytes | None = None, timeout: float = 60):
    return execute(host(server_id), HOST_PATH + command, stdin, timeout)


def check(server_id: str, command: str, stdin: bytes | None = None, timeout: float = 60) -> str:
    return output_of(run(server_id, command, stdin, timeout))


def probe(server_id: str, url: str) -> dict:
    try:
        connect(server_id, url)
        check(server_id, "command -v zoovm")
        check(server_id, f"zoovm get {BASE_VM}")
        os_version = check(server_id, "sw_vers -productVersion").strip()
        cpus, memory = check(server_id, "sysctl -n hw.ncpu hw.memsize").split()
        running = len(running_vms(server_id))
    except Exception as e:
        forget(server_id)
        return {"online": False, "error": str(e)[:500]}
    return {
        "online": True,
        "name": urlparse(url).hostname,
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
    rid = runtime_id(server_id, sandbox_id)
    if len(running_vms(server_id) - {name}) >= MAX_VMS:
        raise RuntimeError(f"this Mac already runs {MAX_VMS} macOS VMs, the most macOS allows")
    if run(server_id, f"zoovm get {name}")[0] != 0:
        check(server_id, f"zoovm clone {BASE_VM} {name} && zoovm set {name} --cpu {CPUS} --memory {MEMORY_MB}")
    check(server_id, f"zoovm stop {name}", timeout=60)
    log = f"~/.zoovm/vms/{name}/run.log"
    check(server_id, f"nohup zoovm run {name} > {log} 2>&1 < /dev/null &")
    url = wait_for_vnc(server_id, name, log)
    wait_for_guest(rid)
    write_env(rid, env)
    return rid, url


def wait_for_vnc(server_id: str, name: str, log: str, timeout: int = 60) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code, out, _ = run(server_id, f"zoovm vnc {name}")
        if code == 0:
            return out.decode().strip()
        if name not in running_vms(server_id):
            raise RuntimeError(run(server_id, f"cat {log}")[1].decode(errors="replace").strip()[-500:] or "VM exited")
        time.sleep(0.5)
    raise RuntimeError("macOS VM did not start its VNC server in time")


def guest_client(rid: str) -> paramiko.SSHClient:
    client = guests.get(rid)
    if alive(client):
        return client
    server_id, name = parse(rid)
    ip = check(server_id, f"zoovm ip {name}").strip()
    tunnel = host(server_id).get_transport().open_channel("direct-tcpip", (ip, 22), ("127.0.0.1", 0), timeout=15)
    client = paramiko.SSHClient()
    # The guest sits on the Mac's private NAT network and is reached only through the host's
    # authenticated SSH connection. Each clone gets fresh host keys, so there is nothing to pin.
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


def guest(rid: str, script: str, stdin: bytes | None = None, timeout: float = 60, root: bool = False):
    command = f"cd {HOME} && {script}"
    if root:
        command = f"sudo -n sh -c {shlex.quote(command)}"
    return execute(guest_client(rid), command, stdin, timeout)


def guest_check(rid: str, script: str, stdin: bytes | None = None, timeout: float = 60, root: bool = False) -> str:
    return output_of(guest(rid, script, stdin, timeout, root))


def guest_bytes(rid: str, script: str, timeout: float) -> bytes:
    code, out, err = guest(rid, script, timeout=timeout)
    if code != 0:
        raise RuntimeError(err.decode(errors="replace").strip() or f"exit code {code}")
    return out


def write_env(rid: str, env: dict[str, str]):
    lines = "".join(f"export {k}={shlex.quote(v)}\n" for k, v in env.items() if re.fullmatch(r"[A-Za-z_]\w*", k))
    guest_check(rid, f"mkdir -p {HOME}/.zoo && umask 077 && cat > {ENV_FILE}", stdin=lines.encode())


def stop(rid: str):
    server_id, name = parse(rid)
    try:
        guest(rid, "shutdown -h now", timeout=10, root=True)
    except Exception:
        pass
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
    """Opens an SSH tunnel to the VM's VNC server, which listens on 127.0.0.1 of the Mac host."""
    server_id, name = parse(rid)
    url = check(server_id, f"zoovm vnc {name}").strip()
    target = urlparse(url)
    channel = host(server_id).get_transport().open_channel(
        "direct-tcpip", (target.hostname, target.port), ("127.0.0.1", 0), timeout=15
    )
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


def apply_apps(rid: str, effects: dict[str, str]):
    lines = []
    for app, effect in effects.items():
        binaries = shlex.quote(f"/Applications/{app}.app/Contents/MacOS")
        owner, mode = (f"{USER}:admin", "755") if effect == "allow" else ("root:wheel", "700")
        lines.append(f"[ -d {binaries} ] && chown -R {owner} {binaries} && chmod -R {mode} {binaries} || true")
    if lines:
        guest_check(rid, "\n".join(lines), root=True)
