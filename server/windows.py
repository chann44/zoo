"""Windows sandboxes: Hyper-V VMs on Windows servers, managed over SSH with windows/zoovm.ps1.

The API uploads the helper scripts in windows/ to ~\\.zoovm on the host. Each guest runs OpenSSH (shell and file
tools), TightVNC (screen, mouse and keyboard) and windows/agent.ps1 in the desktop session (window and app tools).
The guest sits on the host's Hyper-V NAT switch, so everything reaches it through the host's SSH connection.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlparse

import paramiko
from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes

from server.ssh import alive, execute, output_of
from server.vnc import VNC, Channel, authenticate

PREFIX = "windows:"
BASE_VM = os.environ.get("ZOO_WINDOWS_BASE", "zoo-windows-base")
CPUS = int(os.environ.get("ZOO_WINDOWS_CPUS", "4"))
MEMORY_MB = int(os.environ.get("ZOO_WINDOWS_MEMORY_MB", "8192"))
MAX_VMS = int(os.environ.get("ZOO_WINDOWS_MAX_VMS", "4"))
USER = "zoo"
HOME = rf"C:\Users\{USER}"
ENV_DIR = rf"{HOME}\.zoo"
ENV_FILE = rf"{ENV_DIR}\env.ps1"
VNC_PORT = 5900
AGENT_PORT = 7071
HELPER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "windows")
HELPERS = ["zoovm.ps1", "setup.ps1", "agent.ps1"]
SAFE_RULE = re.compile(r"^[A-Za-z0-9.:/_-]+$")
# TightVNC stores its password DES-encrypted with this fixed key.
TIGHTVNC_KEY = bytes.fromhex("e84ad660c4721ae0")

# Reads a length-prefixed script from stdin and runs it; the rest of stdin stays readable through $ZooIn.
# Scripts travel over stdin because cmd.exe, which runs SSH commands on Windows, caps command lines at 8191 chars.
BOOTSTRAP = (
    "$i=[Console]::OpenStandardInput();$h=New-Object byte[] 8;$n=0;"
    "while($n -lt 8){$r=$i.Read($h,$n,8-$n);if($r -le 0){exit 2};$n+=$r};"
    "$l=[int][Text.Encoding]::ASCII.GetString($h);$s=New-Object byte[] $l;$n=0;"
    "while($n -lt $l){$r=$i.Read($s,$n,$l-$n);if($r -le 0){exit 2};$n+=$r};"
    "$ZooIn=$i;. ([ScriptBlock]::Create([Text.Encoding]::UTF8.GetString($s)))"
)
POWERSHELL = (
    "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "
    + base64.b64encode(BOOTSTRAP.encode("utf-16-le")).decode()
)
PREAMBLE = (
    "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';"
    "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n"
    "function Read-ZooInput { $m=New-Object IO.MemoryStream; $ZooIn.CopyTo($m); ,$m.ToArray() }\n"
)

hosts: dict[str, paramiko.SSHClient] = {}
guests: dict[str, paramiko.SSHClient] = {}
urls: dict[str, str] = {}
uploaded: set[str] = set()
vnc_set: set[str] = set()
lock = threading.Lock()


def q(value: str) -> str:
    """Quotes a value as a PowerShell single-quoted string."""
    return "'" + re.sub("['\u2018\u2019\u201a\u201b]", lambda m: m.group() * 2, str(value)) + "'"


def is_vm(runtime_id: str | None) -> bool:
    return bool(runtime_id) and runtime_id.startswith(PREFIX)


def vm_name(sandbox_id: str) -> str:
    return f"zoo-{sandbox_id}"


def runtime_id(server_id: str, sandbox_id: str) -> str:
    return f"{PREFIX}{server_id}:{vm_name(sandbox_id)}"


def parse(runtime_id: str) -> tuple[str, str]:
    server_id, name = runtime_id[len(PREFIX):].split(":", 1)
    return server_id, name


def payload(script: str, data: bytes = b"", cwd: str | None = None) -> bytes:
    body = PREAMBLE
    if cwd:
        body += f"Set-Location -LiteralPath {q(cwd)}\n"
    body += "try {\n" + script + "\n} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }\n"
    encoded = body.encode()
    return f"{len(encoded):08d}".encode() + encoded + data


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
        uploaded.discard(server_id)
    upload_helpers(server_id)
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
        uploaded.discard(server_id)
        client = hosts.pop(server_id, None)
    if client is not None:
        client.close()


def run(server_id: str, script: str, data: bytes = b"", timeout: float = 60):
    return execute(host(server_id), POWERSHELL, payload(script, data), timeout)


def check(server_id: str, script: str, data: bytes = b"", timeout: float = 60) -> str:
    return output_of(run(server_id, script, data, timeout))


def write_host_file(server_id: str, name: str, data: bytes):
    check(
        server_id,
        "$d = Join-Path $env:USERPROFILE '.zoovm'; New-Item -ItemType Directory -Force -Path $d | Out-Null\n"
        f"[IO.File]::WriteAllBytes((Join-Path $d {q(name)}), (Read-ZooInput))",
        data,
    )


def upload_helpers(server_id: str):
    """Copies windows/*.ps1 to the host once per connection, so the host always runs this API's version."""
    if server_id in uploaded:
        return
    for name in HELPERS:
        with open(os.path.join(HELPER_DIR, name), "rb") as f:
            write_host_file(server_id, name, f.read())
    uploaded.add(server_id)


def zoovm(server_id: str, *args, timeout: float = 120):
    host(server_id)
    command = " ".join(a if a.startswith("-") else q(a) for a in map(str, args))
    return run(server_id, f"& (Join-Path $env:USERPROFILE '.zoovm\\zoovm.ps1') {command}\nexit $LASTEXITCODE", timeout=timeout)


def zoovm_check(server_id: str, *args, timeout: float = 120) -> str:
    return output_of(zoovm(server_id, *args, timeout=timeout))


def probe(server_id: str, url: str) -> dict:
    try:
        connect(server_id, url)
        info = json.loads(
            check(
                server_id,
                "$os = Get-CimInstance Win32_OperatingSystem\n"
                "$cs = Get-CimInstance Win32_ComputerSystem\n"
                "$hyperv = [bool](Get-Command Get-VM -ErrorAction SilentlyContinue)\n"
                "if ($hyperv) { Get-VM | Out-Null }\n"
                "ConvertTo-Json -Compress @{ name = $env:COMPUTERNAME; os = \"$($os.Caption) $($os.BuildNumber)\";"
                " cpus = $cs.NumberOfLogicalProcessors; memory = $cs.TotalPhysicalMemory; hyperv = $hyperv }",
            )
        )
        running = len(running_vms(server_id)) if info["hyperv"] else 0
    except Exception as e:
        forget(server_id)
        return {"online": False, "error": str(e)[:500]}
    return {
        "online": True,
        "name": info["name"],
        "os": info["os"].replace("Microsoft ", ""),
        "cpus": int(info["cpus"]),
        "memory_total": int(info["memory"]),
        "docker_version": None,
        "microvm": info["hyperv"],
        "containers_running": running,
    }


def running_vms(server_id: str) -> set[str]:
    return {r["name"] for r in json.loads(zoovm_check(server_id, "list") or "[]") if r["state"] == "running"}


def exists(server_id: str, name: str) -> bool:
    return zoovm(server_id, "get", name)[0] == 0


def start(sandbox_id: str, server, env: dict[str, str]) -> tuple[str, str]:
    """Clones the base VM's latest template on first boot, starts it, and waits until the guest and its agent answer."""
    server_id, name = server.id, vm_name(sandbox_id)
    connect(server_id, server.docker_url)
    rid = runtime_id(server_id, sandbox_id)
    created = exists(server_id, name)
    if not created and zoovm(server_id, "sealed", BASE_VM)[0] != 0:
        raise RuntimeError("the base VM isn't ready yet: finish its setup and stop it under Remote Servers, then start again")
    if len(running_vms(server_id) - {name}) >= MAX_VMS:
        raise RuntimeError(f"this server already runs {MAX_VMS} Windows VMs (ZOO_WINDOWS_MAX_VMS)")
    if not created:
        zoovm_check(server_id, "clone", BASE_VM, name, "-Cpu", str(CPUS), "-Memory", str(MEMORY_MB))
    zoovm_check(server_id, "start", name)
    wait_for_guest(rid)
    set_vnc_password(rid)
    write_env(rid, env)
    return rid, f"vnc://{guest_ip(rid)}:{VNC_PORT}"


def guest_ip(rid: str) -> str:
    server_id, name = parse(rid)
    return zoovm_check(server_id, "ip", name).strip()


def tunnel(rid: str, port: int, address: str | None = None):
    server_id, _ = parse(rid)
    target = (address or guest_ip(rid), port)
    return host(server_id).get_transport().open_channel("direct-tcpip", target, ("127.0.0.1", 0), timeout=15)


def guest_client(rid: str) -> paramiko.SSHClient:
    client = guests.get(rid)
    if alive(client):
        return client
    ip = guest_ip(rid)
    client = paramiko.SSHClient()
    # The guest sits on the host's private Hyper-V NAT switch, reachable only through the host's SSH connection,
    # and every clone shares the base VM's host keys, so there is nothing useful to pin.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username=USER, sock=tunnel(rid, 22, ip), timeout=15, banner_timeout=15, auth_timeout=15)
    client.get_transport().set_keepalive(30)
    guests[rid] = client
    return client


def guest(rid: str, script: str, data: bytes = b"", timeout: float = 60):
    return execute(guest_client(rid), POWERSHELL, payload(script, data, cwd=HOME), timeout)


def guest_check(rid: str, script: str, data: bytes = b"", timeout: float = 60) -> str:
    return output_of(guest(rid, script, data, timeout))


def guest_json(rid: str, script: str, timeout: float = 60):
    return json.loads(guest_check(rid, script, timeout=timeout))


def guest_raw(rid: str, command: str, stdin: bytes | None = None, timeout: float = 60):
    """Runs a cmd.exe command line in the guest, for tools like tar that stream binary data."""
    return execute(guest_client(rid), command, stdin, timeout)


def agent(rid: str, script: str, timeout: float = 30) -> str:
    """Runs a PowerShell script in the guest's desktop session through windows/agent.ps1."""
    channel = guest_client(rid).get_transport().open_channel(
        "direct-tcpip", ("127.0.0.1", AGENT_PORT), ("127.0.0.1", 0), timeout=15
    )
    try:
        channel.settimeout(timeout)
        channel.sendall(base64.b64encode(script.encode()) + b"\r\n")
        reply = b""
        while not reply.endswith(b"\n"):
            chunk = channel.recv(65536)
            if not chunk:
                break
            reply += chunk
    finally:
        channel.close()
    status, _, body = reply.strip().decode().partition(" ")
    text = base64.b64decode(body).decode(errors="replace") if body else ""
    if status != "ok":
        raise RuntimeError(text.strip() or "the desktop agent did not answer")
    return text.strip()


def agent_json(rid: str, script: str, timeout: float = 30):
    return json.loads(agent(rid, script, timeout) or "null")


def wait_for_guest(rid: str, timeout: int = 600):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            if guest(rid, "exit 0", timeout=15)[0] == 0 and agent(rid, "'ok'", timeout=10) == "ok":
                return
        except Exception as e:
            error = e
            client = guests.pop(rid, None)
            if client is not None:
                client.close()
        time.sleep(3)
    raise RuntimeError(f"could not reach the Windows guest: {error}")


def vnc_password(rid: str) -> str:
    digest = hmac.new(os.environ.get("JWT_SECRET", "").encode(), rid.encode(), hashlib.sha256).digest()
    return base64.b32encode(digest).decode().lower()[:8]


def set_vnc_password(rid: str):
    """Gives the guest's TightVNC server this VM's own password; clones start with the base VM's."""
    encryptor = Cipher(TripleDES(TIGHTVNC_KEY * 3), modes.ECB()).encryptor()
    stored = encryptor.update(vnc_password(rid).encode().ljust(8, b"\0")) + encryptor.finalize()
    guest_check(
        rid,
        "$k = 'HKLM:\\SOFTWARE\\TightVNC\\Server'\n"
        f"Set-ItemProperty -Path $k -Name Password -Type Binary -Value ([byte[]]({','.join(str(b) for b in stored)}))\n"
        "Set-ItemProperty -Path $k -Name UseVncAuthentication -Type DWord -Value 1\n"
        "Restart-Service tvnserver",
    )
    vnc_set.add(rid)


def write_env(rid: str, env: dict[str, str]):
    lines = "".join(f"$env:{k} = {q(v)}\n" for k, v in env.items() if re.fullmatch(r"[A-Za-z_]\w*", k))
    guest_check(
        rid,
        f"New-Item -ItemType Directory -Force -Path {q(ENV_DIR)} | Out-Null\n"
        f"[IO.File]::WriteAllBytes({q(ENV_FILE)}, (Read-ZooInput))",
        lines.encode(),
    )


def close_guest(rid: str):
    vnc_set.discard(rid)
    client = guests.pop(rid, None)
    if client is not None:
        client.close()


def stop(rid: str):
    server_id, name = parse(rid)
    close_guest(rid)
    zoovm_check(server_id, "stop", name, "-Timeout", "45", timeout=120)


def delete(sandbox_id: str, server):
    connect(server.id, server.docker_url)
    zoovm_check(server.id, "delete", vm_name(sandbox_id), timeout=180)


def is_running(rid: str) -> bool:
    server_id, name = parse(rid)
    return name in running_vms(server_id)


def vnc_channel(rid: str):
    """Connects to the guest's VNC server through the host's SSH connection."""
    if rid not in vnc_set:
        set_vnc_password(rid)
    channel = tunnel(rid, VNC_PORT)
    channel.settimeout(30)
    return channel, vnc_password(rid)


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


def windows_path(path: str) -> str:
    if '"' in path:
        raise ValueError("paths can't contain double quotes")
    return path.replace("/", "\\").rstrip("\\")


def tar_output(rid: str, command: str, timeout: float) -> bytes:
    code, out, err = guest_raw(rid, command, timeout=timeout)
    # bsdtar exits 1 when it skipped files Windows keeps locked, like the registry hive; the archive is still good.
    if code != 0 and not (code == 1 and out):
        raise RuntimeError(err.decode(errors="replace").strip() or f"exit code {code}")
    return out


def export_dir(rid: str, path: str) -> bytes:
    parent, base = os.path.split(windows_path(path).replace("\\", "/"))
    return tar_output(rid, f'tar.exe -cf - -C "{windows_path(parent)}" "{base}"', 600)


def import_dir(rid: str, parent: str, data: bytes):
    parent = windows_path(parent)
    output_of(guest_raw(rid, f'mkdir "{parent}" 2>nul & tar.exe -xf - -C "{parent}"', data, 600))


def export_home(rid: str):
    excludes = " ".join(f'--exclude "{USER}/{p}"' for p in ["AppData/Local", "NTUSER.DAT*", "ntuser.dat*", "ntuser.ini"])
    yield tar_output(rid, f"tar.exe -cf - {excludes} -C C:\\Users {USER}", 3600)


def import_home(rid: str, data: bytes):
    output_of(guest_raw(rid, "tar.exe -xf - -C C:\\Users", data, 3600))


def apply_network(rid: str, default_action: str, allow_dns: bool, rules: list[tuple[str, str, str]]):
    """Windows Firewall outbound rules. Unlike iptables, a block rule wins over an allow rule whatever their order."""
    lines = [
        "Remove-NetFirewallRule -Group 'zoo-policy' -ErrorAction SilentlyContinue",
        (
            "Set-NetFirewallProfile -All -Enabled True "
            f"-DefaultOutboundAction {'Block' if default_action == 'deny' else 'Allow'}"
        ),
        "function Rule($name, $action, $address, $protocol, $port) {",
        "  $a = @{ Group = 'zoo-policy'; DisplayName = \"zoo $name\"; Direction = 'Outbound'; Action = $action }",
        "  if ($address) { $a.RemoteAddress = $address }",
        "  if ($protocol) { $a.Protocol = $protocol; $a.RemotePort = $port }",
        "  New-NetFirewallRule @a | Out-Null",
        "}",
        "Rule dhcp Allow $null UDP 67",
        f"Rule dns-udp {'Allow' if allow_dns else 'Block'} $null UDP 53",
        f"Rule dns-tcp {'Allow' if allow_dns else 'Block'} $null TCP 53",
    ]
    for rule_type, value, effect in rules:
        if not SAFE_RULE.match(value):
            raise ValueError(f"invalid network rule value {value!r}")
        action = "Allow" if effect == "allow" else "Block"
        if rule_type == "domain":
            lines.append(
                f"$ips = @(Resolve-DnsName -Type A -Name {q(value)} -ErrorAction SilentlyContinue | "
                "Where-Object IPAddress | ForEach-Object IPAddress)\n"
                f"if ($ips) {{ Rule {q(value)} {action} $ips }}"
            )
        else:
            lines.append(f"Rule {q(value)} {action} {q(value)}")
    guest_check(rid, "\n".join(lines))


def apply_apps(rid: str, effects: dict[str, str]):
    """Blocks an app's .exe from starting with an Image File Execution Options debugger that doesn't exist."""
    lines = ["$ifeo = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Image File Execution Options'"]
    for binary, effect in effects.items():
        if not re.fullmatch(r"[\w .+-]+\.exe", binary, re.IGNORECASE):
            continue
        key = f"(Join-Path $ifeo {q(binary)})"
        if effect == "allow":
            lines.append(f"Remove-ItemProperty -Path {key} -Name Debugger -ErrorAction SilentlyContinue")
        else:
            lines.append(f"New-Item -Path {key} -Force | Out-Null")
            lines.append(f"Set-ItemProperty -Path {key} -Name Debugger -Value 'C:\\zoo\\blocked-by-policy.exe'")
    if len(lines) > 1:
        guest_check(rid, "\n".join(lines))


INSTALL_LOG = "install.log"
PHASES = ("downloading Windows", "preparing disk", "using ", "applying Windows image", "first boot", "installed")


def base_id(server_id: str) -> str:
    return f"{PREFIX}{server_id}:{BASE_VM}"


def ready_marker() -> str:
    return f"(Join-Path $env:USERPROFILE '.zoovm\\vms\\{BASE_VM}\\zoo-ready')"


def base_ready(server_id: str, running: bool) -> bool:
    if run(server_id, f"if (-not (Test-Path {ready_marker()})) {{ exit 1 }}")[0] == 0:
        return True
    if not running:
        return False
    try:
        ok = guest(base_id(server_id), "exit 0", timeout=10)[0] == 0 and agent(base_id(server_id), "'ok'", 10) == "ok"
    except Exception:
        close_guest(base_id(server_id))
        return False
    if ok:
        check(server_id, f"Set-Content -Path {ready_marker()} -Value ready")
    return ok


def base_status(server_id: str) -> dict:
    """State of the server's base VM: missing, installing, failed, stopped or running."""
    installing = zoovm(server_id, "installing", BASE_VM)[0] == 0
    log = run(
        server_id,
        f"$f = Join-Path $env:USERPROFILE '.zoovm\\{INSTALL_LOG}'\n"
        "if (Test-Path $f) { $t = [IO.File]::ReadAllText($f); $t.Substring([Math]::Max(0, $t.Length - 4000)) }",
    )[1].decode(errors="replace")
    lines = [line.strip() for line in re.split(r"[\r\n]+", log) if line.strip()]
    last = lines[-1] if lines else ""
    if installing:
        phase = next((line for line in reversed(lines) if line.startswith(PHASES)), "starting")
        found = re.findall(r"(\d+(?:\.\d+)?)%", last)
        return {"state": "installing", "progress": float(found[-1]) if found else None, "message": phase}
    if not exists(server_id, BASE_VM):
        failed = "zoovm:" in log
        return {"state": "failed" if failed else "missing", "progress": None, "message": last[-300:] if failed else None}
    running = BASE_VM in running_vms(server_id)
    ready = base_ready(server_id, running)
    message = None if ready or not running else "Windows is finishing setup (C:\\zoo\\setup.log in the VM)"
    return {"state": "running" if running else "stopped", "progress": None, "message": message, "ready": ready}


def base_install(server_id: str, iso: str, edition: str | None = None):
    from server.macos import public_key

    write_host_file(server_id, "authorized_keys", (public_key() + "\n").encode())
    args = ["spawn", BASE_VM, "-Iso", iso] + (["-Edition", edition] if edition else [])
    zoovm_check(server_id, *args)


def base_start(server_id: str) -> str:
    zoovm_check(server_id, "start", BASE_VM)
    return ""


def base_stop(server_id: str):
    """Shuts the base VM down and, once its setup is done, seals its disk as the template new sandboxes clone."""
    close_guest(base_id(server_id))
    zoovm_check(server_id, "stop", BASE_VM, "-Timeout", "120", timeout=180)
    if base_ready(server_id, running=False):
        zoovm_check(server_id, "seal", BASE_VM, timeout=300)
