"""Windows sandboxes: Hyper-V VMs on Windows servers, managed over SSH with windows/zoovm.ps1.

The API uploads the helper scripts in windows/ to ~\\.zoovm on the host. Each guest runs OpenSSH (shell and file
tools), TightVNC (screen, mouse and keyboard) and windows/agent.ps1 in the desktop session (window and app tools).
The guest sits on the host's Hyper-V NAT switch, so everything reaches it through the host's SSH connection.

When zoo-guest is connected (installed at every boot, see install_guest), shell, file and window tools go through it
instead, in the desktop session; admin changes (network and app policy, VNC password) stay on SSH.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlparse

import paramiko
from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes

from server import egress
from server.guest import guest_endpoint, guest_env, hub
from server.ssh import alive, execute, load_known_hosts, output_of
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
ROOT = os.path.dirname(os.path.dirname(__file__))
HELPER_DIR = os.path.join(ROOT, "windows")
GUEST_BINARY = os.environ.get(
    "ZOO_GUEST_WINDOWS_BINARY", os.path.join(ROOT, "guest", "dist", "zoo-guest-windows-amd64.exe")
)
GUEST_TASK = "zoo-guest"
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
POWERSHELL_ARGV = [
    "powershell.exe",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-EncodedCommand",
    base64.b64encode(BOOTSTRAP.encode("utf-16-le")).decode(),
]
POWERSHELL = " ".join(POWERSHELL_ARGV)
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
    server_id, name = runtime_id[len(PREFIX) :].split(":", 1)
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
        load_known_hosts(client)
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
    return run(
        server_id, f"& (Join-Path $env:USERPROFILE '.zoovm\\zoovm.ps1') {command}\nexit $LASTEXITCODE", timeout=timeout
    )


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
                'ConvertTo-Json -Compress @{ name = $env:COMPUTERNAME; os = "$($os.Caption) $($os.BuildNumber)";'
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
        raise RuntimeError(
            "the base VM isn't ready yet: finish its setup and stop it under Remote Servers, then start again"
        )
    if len(running_vms(server_id) - {name}) >= MAX_VMS:
        raise RuntimeError(f"this server already runs {MAX_VMS} Windows VMs (ZOO_WINDOWS_MAX_VMS)")
    if not created:
        zoovm_check(server_id, "clone", BASE_VM, name, "-Cpu", str(CPUS), "-Memory", str(MEMORY_MB))
    if name not in running_vms(server_id):
        # an earlier boot's port ACLs may name the host's address on a switch that has since changed; enforce()
        # puts the current ones back once the guest answers
        check(server_id, CLEAR_ACLS.replace("__VM__", q(name)))
        zoovm_check(server_id, "start", name)
    wait_for_guest(rid)
    set_vnc_password(rid)
    write_env(rid, env)
    hub.bind(rid, sandbox_id)
    install_guest(rid, sandbox_id)
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


def connected(rid: str, service: str, ssh: bool = False):
    """zoo-guest for this VM when it offers service, else None for the SSH and agent.ps1 path."""
    agent = None if ssh else hub.for_runtime(rid)
    return agent if agent is not None and agent.has(service) else None


def guest(rid: str, script: str, data: bytes = b"", timeout: float = 60, ssh: bool = False):
    """Runs a PowerShell script in the guest: through zoo-guest in the desktop session when it's connected,
    else over SSH. ssh=True is for admin changes, which stay on the SSH session."""
    stdin = payload(script, data, cwd=HOME)
    agent = connected(rid, "exec", ssh)
    if agent is not None:
        return agent.exec_run(POWERSHELL_ARGV, stdin=stdin, timeout=timeout)
    return execute(guest_client(rid), POWERSHELL, stdin, timeout)


def guest_check(rid: str, script: str, data: bytes = b"", timeout: float = 60, ssh: bool = False) -> str:
    return output_of(guest(rid, script, data, timeout, ssh))


def guest_json(rid: str, script: str, timeout: float = 60):
    return json.loads(guest_check(rid, script, timeout=timeout))


def guest_raw(rid: str, argv: list[str], stdin: bytes | None = None, timeout: float = 60):
    """Runs a program in the guest without PowerShell, for tools like tar that stream binary data."""
    agent = connected(rid, "exec")
    if agent is not None:
        return agent.exec_run(argv, stdin=stdin or b"", timeout=timeout)
    return execute(guest_client(rid), subprocess.list2cmdline(argv), stdin, timeout)


def agent(rid: str, script: str, timeout: float = 30) -> str:
    """Runs a PowerShell script in the guest's desktop session through windows/agent.ps1."""
    channel = (
        guest_client(rid)
        .get_transport()
        .open_channel("direct-tcpip", ("127.0.0.1", AGENT_PORT), ("127.0.0.1", 0), timeout=15)
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


def desktop(rid: str, script: str, timeout: float = 30) -> str:
    """Runs a PowerShell script in the desktop session, so the windows it starts show up: through zoo-guest, which
    runs there, or agent.ps1."""
    if connected(rid, "exec") is not None:
        return guest_check(rid, script, timeout=timeout).strip()
    return agent(rid, script, timeout)


def desktop_json(rid: str, script: str, timeout: float = 30):
    return json.loads(desktop(rid, script, timeout) or "null")


def window(rid: str, action: str, window_id: str = "", cmd: int = 0):
    """Lists (action "list") or acts on top-level windows: "show" with a ShowWindow cmd, "focus" or "close"."""
    guest_agent = connected(rid, "windows")
    if guest_agent is not None:
        result, _ = guest_agent.call("window", {"action": action, "id": str(window_id), "cmd": cmd}, timeout=30)
        return result.get("windows")
    if action == "list":
        return agent_json(rid, "ConvertTo-Json -Compress -InputObject @([ZooWin]::List())") or []
    call = {"show": f"Show({q(window_id)}, {int(cmd)})", "focus": f"Focus({q(window_id)})"}.get(
        action, f"Close({q(window_id)})"
    )
    agent(rid, f"[ZooWin]::{call}")


INSTALL_GUEST = r"""
$dir = Join-Path $HOME '.zoo'
$exe = Join-Path $dir 'bin\zoo-guest.exe'
$envFile = Join-Path $dir 'guest.env'
$data = Read-ZooInput
$split = [Array]::IndexOf($data, [byte]0)
function Write-Part($path, $offset, $count) { $f = [IO.File]::Create($path); $f.Write($data, $offset, $count); $f.Close() }
Write-Part $envFile 0 $split
if ($data.Length -gt $split + 1) {
    Stop-ScheduledTask -TaskName __TASK__ -ErrorAction SilentlyContinue
    Get-Process -Name zoo-guest -ErrorAction SilentlyContinue | Stop-Process -Force
    New-Item -ItemType Directory -Force -Path (Split-Path $exe) | Out-Null
    Write-Part $exe ($split + 1) ($data.Length - $split - 1)
}
$action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $HOME `
    -Argument ('-env "{0}" -log "{1}"' -f $envFile, (Join-Path $dir 'guest.log'))
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName __TASK__ -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName __TASK__
"""


def install_guest(rid: str, sandbox_id: str, timeout: float = 15):
    """Copies zoo-guest into the VM when it changed, writes its config, and (re)starts it as a scheduled task in the
    zoo user's desktop session, where agent.ps1 runs. Every boot does this, so clones of an older base VM get it."""
    env = guest_env(sandbox_id, remote=True)
    if not env or not os.path.exists(GUEST_BINARY):
        return
    with open(GUEST_BINARY, "rb") as f:
        binary = f.read()
    installed = guest_check(
        rid,
        "$exe = Join-Path $HOME '.zoo\\bin\\zoo-guest.exe'\n"
        "if (Test-Path -LiteralPath $exe) { (Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash }",
        ssh=True,
    )
    if installed.strip().lower() == hashlib.sha256(binary).hexdigest():
        binary = b""
    # the env file, a NUL, then the binary when it needs copying
    data = "".join(f"{k}={v}\n" for k, v in env.items()).encode() + b"\0" + binary
    guest_check(rid, INSTALL_GUEST.replace("__TASK__", q(GUEST_TASK)), data, timeout=120, ssh=True)
    deadline = time.monotonic() + timeout
    while hub.for_sandbox(sandbox_id) is None and time.monotonic() < deadline:
        time.sleep(0.25)


def wait_for_guest(rid: str, timeout: int = 600):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            if guest(rid, "exit 0", timeout=15, ssh=True)[0] == 0 and agent(rid, "'ok'", timeout=10) == "ok":
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
        ssh=True,
    )
    vnc_set.add(rid)


def write_env(rid: str, env: dict[str, str]):
    lines = "".join(f"$env:{k} = {q(v)}\n" for k, v in env.items() if re.fullmatch(r"[A-Za-z_]\w*", k))
    guest_check(
        rid,
        f"New-Item -ItemType Directory -Force -Path {q(ENV_DIR)} | Out-Null\n"
        f"[IO.File]::WriteAllBytes({q(ENV_FILE)}, (Read-ZooInput))",
        lines.encode(),
        ssh=True,
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
    forget_policy(server_id, name)


def delete(sandbox_id: str, server):
    connect(server.id, server.docker_url)
    zoovm_check(server.id, "delete", vm_name(sandbox_id), timeout=180)
    forget_policy(server.id, vm_name(sandbox_id))


def forget_policy(server_id: str, name: str):
    run(
        server_id,
        f"Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path {EGRESS_DIR} {q(egress.file_name(name))})",
    )


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


def tar_output(rid: str, argv: list[str], timeout: float) -> bytes:
    code, out, err = guest_raw(rid, argv, timeout=timeout)
    # bsdtar exits 1 when it skipped files Windows keeps locked, like the registry hive; the archive is still good.
    if code != 0 and not (code == 1 and out):
        raise RuntimeError(err.decode(errors="replace").strip() or f"exit code {code}")
    return out


def export_dir(rid: str, path: str) -> bytes:
    parent, base = os.path.split(windows_path(path).replace("\\", "/"))
    return tar_output(rid, ["tar.exe", "-cf", "-", "-C", windows_path(parent), base], 600)


def import_dir(rid: str, parent: str, data: bytes):
    parent = windows_path(parent)
    guest_check(rid, f"New-Item -ItemType Directory -Force -Path {q(parent)} | Out-Null")
    output_of(guest_raw(rid, ["tar.exe", "-xf", "-", "-C", parent], data, 600))


def export_home(rid: str):
    excludes = [f"--exclude={USER}/{p}" for p in ["AppData/Local", "NTUSER.DAT*", "ntuser.dat*", "ntuser.ini"]]
    yield tar_output(rid, ["tar.exe", "-cf", "-", *excludes, "-C", "C:\\Users", USER], 3600)


def import_home(rid: str, data: bytes):
    output_of(guest_raw(rid, ["tar.exe", "-xf", "-", "-C", "C:\\Users"], data, 3600))


EGRESS_DIR = "(Join-Path $env:USERPROFILE '.zoovm\\egress')"
EGRESS_TASK = "zoo-egress"

CLEAR_ACLS = "Get-VMNetworkAdapterExtendedAcl -VMName __VM__ | Remove-VMNetworkAdapterExtendedAcl"

# On the host: writes the VM's policy for the egress daemon and puts Hyper-V port ACLs on the VM's adapter. A
# filtered VM may only reach the daemon's proxy, the API and DHCP (and DNS when allowed), plus ip rules that allow,
# and answer the host's SSH and VNC; everything else it sends is dropped at the switch, outside the VM.
# Prints the host's address on the VM's switch, where the proxy listens.
HOST_POLICY = r"""
$vm = __VM__
$dir = __DIR__
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$keep = @(@((Get-VM | Where-Object State -eq 'Running').Name) + $vm | ForEach-Object { "$_.json" })
Get-ChildItem -Path $dir -Filter *.json | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
$tmp = Join-Path $dir "$vm.json.tmp"
[IO.File]::WriteAllBytes($tmp, (Read-ZooInput))
Move-Item -Force -Path $tmp -Destination (Join-Path $dir "$vm.json")
$switch = (Get-VMNetworkAdapter -VMName $vm | Select-Object -First 1).SwitchName
$hostIp = (Get-NetIPAddress -InterfaceAlias "vEthernet ($switch)" -AddressFamily IPv4 | Select-Object -First 1).IPAddress
if (-not $hostIp) { throw "no host address on switch '$switch'" }
Get-VMNetworkAdapterExtendedAcl -VMName $vm | Remove-VMNetworkAdapterExtendedAcl
$script:weight = @{ Deny = 1000; Allow = 10; System = 2000 }
function Acl($kind, $extra) {
    $action = $(if ($kind -eq 'Deny') { 'Deny' } else { 'Allow' })
    $script:weight[$kind] += 1
    Add-VMNetworkAdapterExtendedAcl -VMName $vm -Direction Outbound -Action $action -Weight $script:weight[$kind] @extra |
        Out-Null
}
if (__FILTERED__) {
    Add-VMNetworkAdapterExtendedAcl -VMName $vm -Direction Outbound -Action Deny -Weight 1 | Out-Null
    Acl System @{ Protocol = 'UDP'; RemotePort = '67' }
    Acl System @{ RemoteIPAddress = $hostIp; Protocol = 'TCP'; RemotePort = '__PROXY_PORT__' }
    Acl System @{ RemoteIPAddress = $hostIp; Protocol = 'TCP'; LocalPort = '22' }
    Acl System @{ RemoteIPAddress = $hostIp; Protocol = 'TCP'; LocalPort = '__VNC_PORT__' }
    if (__DNS__) {
        Acl System @{ RemoteIPAddress = $hostIp; Protocol = 'UDP'; RemotePort = '53' }
        Acl System @{ RemoteIPAddress = $hostIp; Protocol = 'TCP'; RemotePort = '53' }
    }
    foreach ($e in @(__ALWAYS__)) {
        $ip, $port = $e.Split('|')
        Acl System @{ RemoteIPAddress = $ip; Protocol = 'TCP'; RemotePort = $port }
    }
    foreach ($c in @(__ALLOW__)) { Acl Allow @{ RemoteIPAddress = $c } }
}
foreach ($c in @(__DENY__)) { Acl Deny @{ RemoteIPAddress = $c } }
$hostIp
"""

ENSURE_EGRESS = r"""
$bin = Join-Path $env:USERPROFILE '.zoovm\bin'
$exe = Join-Path $bin 'zoo-guest.exe'
$dir = __DIR__
New-Item -ItemType Directory -Force -Path $bin, $dir | Out-Null
$data = Read-ZooInput
if ($data.Length -gt 0) {
    Stop-ScheduledTask -TaskName __TASK__ -ErrorAction SilentlyContinue
    Get-Process -Name zoo-guest -ErrorAction SilentlyContinue | Where-Object Path -eq $exe | Stop-Process -Force
    [IO.File]::WriteAllBytes($exe, $data)
}
if (-not (Get-NetFirewallRule -DisplayName 'zoo egress' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName 'zoo egress' -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort __PROXY_PORT__ -Program $exe | Out-Null
}
if (-not (Get-ScheduledTask -TaskName __TASK__ -ErrorAction SilentlyContinue)) {
    $action = New-ScheduledTaskAction -Execute $exe `
        -Argument ('-egress "{0}" -log "{1}"' -f $dir, (Join-Path $env:USERPROFILE '.zoovm\egress.log'))
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName __TASK__ -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Force | Out-Null
}
if ((Get-ScheduledTask -TaskName __TASK__).State -ne 'Running') { Start-ScheduledTask -TaskName __TASK__ }
"""

# In the guest: points WinINet, WinHTTP and command-line tools at the host's proxy, the only way out of a filtered VM.
GUEST_PROXY = r"""
$proxy = __PROXY__
$inet = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
if ($proxy) {
    Set-ItemProperty -Path $inet -Name ProxyEnable -Value 1 -Type DWord
    Set-ItemProperty -Path $inet -Name ProxyServer -Value $proxy
    Set-ItemProperty -Path $inet -Name ProxyOverride -Value '<local>'
    netsh winhttp set proxy proxy-server="$proxy" bypass-list="<local>" | Out-Null
    [Environment]::SetEnvironmentVariable('HTTP_PROXY', "http://$proxy", 'Machine')
    [Environment]::SetEnvironmentVariable('HTTPS_PROXY', "http://$proxy", 'Machine')
    [Environment]::SetEnvironmentVariable('NO_PROXY', 'localhost,127.0.0.1', 'Machine')
} else {
    Set-ItemProperty -Path $inet -Name ProxyEnable -Value 0 -Type DWord
    netsh winhttp reset proxy | Out-Null
    foreach ($n in 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY') { [Environment]::SetEnvironmentVariable($n, $null, 'Machine') }
}
"""


def ps_list(values: list[str]) -> str:
    """The inside of @(...): empty stays empty, where $null would be one item."""
    return ", ".join(q(v) for v in values)


def ensure_egress(server_id: str):
    """Runs the host's egress daemon (guest/egress.go) as a scheduled task, copying this API's build over when it
    changed."""
    with open(GUEST_BINARY, "rb") as f:
        binary = f.read()
    installed = check(
        server_id,
        "$exe = Join-Path $env:USERPROFILE '.zoovm\\bin\\zoo-guest.exe'\n"
        "if (Test-Path -LiteralPath $exe) { (Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash }",
    )
    if installed.strip().lower() == hashlib.sha256(binary).hexdigest():
        binary = b""
    script = (
        ENSURE_EGRESS.replace("__DIR__", EGRESS_DIR)
        .replace("__TASK__", q(EGRESS_TASK))
        .replace("__PROXY_PORT__", str(egress.PROXY_PORT))
    )
    check(server_id, script, binary, timeout=120)


def apply_network(rid: str, default_action: str, allow_dns: bool, rules: list[tuple[str, str, str]]):
    """Enforced on the host: the egress daemon's proxy decides names, and Hyper-V port ACLs keep a filtered VM from
    going around it. Inside the VM, the proxy settings and Windows Firewall are a second layer."""
    for _, value, _ in rules:
        if not SAFE_RULE.match(value):
            raise ValueError(f"invalid network rule value {value!r}")
    server_id, name = parse(rid)
    ensure_egress(server_id)
    filtered = egress.proxied(default_action, rules)
    endpoints = egress.always(guest_endpoint())
    data = egress.policy(rid, [guest_ip(rid)], default_action, allow_dns, rules, endpoints)
    addresses = [(t, v, e) for t, v, e in rules if t != "domain"]
    script = (
        HOST_POLICY.replace("__VM__", q(name))
        .replace("__DIR__", EGRESS_DIR)
        .replace("__FILTERED__", "$true" if filtered else "$false")
        .replace("__DNS__", "$true" if allow_dns else "$false")
        .replace("__PROXY_PORT__", str(egress.PROXY_PORT))
        .replace("__VNC_PORT__", str(VNC_PORT))
        .replace("__ALWAYS__", ps_list([f"{e['ip']}|{int(e['port'])}" for e in endpoints]))
        .replace("__ALLOW__", ps_list([v for _, v, e in addresses if e == "allow"]))
        .replace("__DENY__", ps_list([v for _, v, e in addresses if e != "allow"]))
    )
    host_ip = check(server_id, script, data).strip().splitlines()[-1]
    proxy = f"{host_ip}:{egress.PROXY_PORT}" if filtered else ""
    lines = [
        GUEST_PROXY.replace("__PROXY__", q(proxy)),
        "Remove-NetFirewallRule -Group 'zoo-policy' -ErrorAction SilentlyContinue",
        (
            "Set-NetFirewallProfile -All -Enabled True "
            f"-DefaultOutboundAction {'Block' if default_action == 'deny' or filtered else 'Allow'}"
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
        *guest_rule(),
    ]
    if filtered:
        lines.append(f"Rule proxy Allow {q(host_ip)} TCP {egress.PROXY_PORT}")
    # names are the host proxy's to decide; here only addresses. A block rule wins over an allow rule.
    for _, value, effect in addresses:
        lines.append(f"Rule {q(value)} {'Allow' if effect == 'allow' else 'Block'} {q(value)}")
    guest_check(rid, "\n".join(lines), ssh=True)


def guest_rule() -> list[str]:
    """Lets zoo-guest reach the API whatever the policy says. A block rule for the same address still wins."""
    endpoint = guest_endpoint()
    if endpoint is None or not SAFE_RULE.match(endpoint[0]):
        return []
    host, port = endpoint
    return [
        f"$ips = @(try {{ [Net.Dns]::GetHostAddresses({q(host)}) | ForEach-Object IPAddressToString }} catch {{}})",
        f"if ($ips) {{ Rule zoo-guest Allow $ips TCP {port} }}",
    ]


# Store (packaged) apps start through their package, not an .exe Image File Execution Options can catch, so they're
# denied with AppLocker packaged-app rules. Enforcing them needs an edition with AppLocker (Enterprise or Education).
APPLOCKER = r"""
$rules = foreach ($family in @(__DENY__)) {
    $pkg = Get-AppxPackage | Where-Object PackageFamilyName -eq $family | Select-Object -First 1
    if (-not $pkg) { continue }
    Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*\WindowsApps\$($pkg.PackageFullName)\*" } |
        Stop-Process -Force
    ('<FilePublisherRule Id="{0}" Name="zoo deny {1}" Description="" UserOrGroupSid="S-1-1-0" Action="Deny">' +
        '<Conditions><FilePublisherCondition PublisherName="{2}" ProductName="{1}" BinaryName="*">' +
        '<BinaryVersionRange LowSection="0.0.0.0" HighSection="*" /></FilePublisherCondition></Conditions>' +
        '</FilePublisherRule>') -f [guid]::NewGuid(), [Security.SecurityElement]::Escape($pkg.Name),
        [Security.SecurityElement]::Escape($pkg.Publisher)
}
if ($rules) {
    # enforcing a collection blocks whatever it doesn't allow, so every other packaged app is allowed first
    $collection = '<RuleCollection Type="Appx" EnforcementMode="Enabled">' +
        '<FilePublisherRule Id="a9e18c21-ff8f-43cf-b9fc-db40eed693ba" Name="All signed packaged apps" ' +
        'Description="" UserOrGroupSid="S-1-1-0" Action="Allow"><Conditions>' +
        '<FilePublisherCondition PublisherName="*" ProductName="*" BinaryName="*">' +
        '<BinaryVersionRange LowSection="0.0.0.0" HighSection="*" /></FilePublisherCondition></Conditions>' +
        '</FilePublisherRule>' + ($rules -join '') + '</RuleCollection>'
} else {
    $collection = '<RuleCollection Type="Appx" EnforcementMode="NotConfigured" />'
}
$path = Join-Path $env:TEMP 'zoo-applocker.xml'
Set-Content -Path $path -Value ('<AppLockerPolicy Version="1">' + $collection + '</AppLockerPolicy>') -Encoding UTF8
Set-AppLockerPolicy -XmlPolicy $path
if ($rules) {
    sc.exe config AppIDSvc start= auto | Out-Null
    Start-Service AppIDSvc
}
"""
PACKAGED = re.compile(r"^([\w.-]+_[a-z0-9]+)![\w.-]+$", re.IGNORECASE)


def apply_apps(rid: str, effects: dict[str, str]):
    """Blocks an app's .exe from starting with an Image File Execution Options debugger that doesn't exist, and a
    Store app with an AppLocker rule for its package."""
    lines = ["$ifeo = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Image File Execution Options'"]
    packaged = {}
    for binary, effect in effects.items():
        if match := PACKAGED.match(binary):
            packaged[match.group(1)] = effect
            continue
        if not re.fullmatch(r"[\w .+-]+\.exe", binary, re.IGNORECASE):
            continue
        key = f"(Join-Path $ifeo {q(binary)})"
        if effect == "allow":
            lines.append(f"Remove-ItemProperty -Path {key} -Name Debugger -ErrorAction SilentlyContinue")
        else:
            lines.append(f"New-Item -Path {key} -Force | Out-Null")
            lines.append(f"Set-ItemProperty -Path {key} -Name Debugger -Value 'C:\\zoo\\blocked-by-policy.exe'")
    if packaged:
        lines.append(APPLOCKER.replace("__DENY__", ps_list([f for f, e in packaged.items() if e != "allow"])))
    if len(lines) > 1:
        guest_check(rid, "\n".join(lines), ssh=True)


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
        return {
            "state": "failed" if failed else "missing",
            "progress": None,
            "message": last[-300:] if failed else None,
        }
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
