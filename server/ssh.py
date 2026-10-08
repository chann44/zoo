"""SSH command execution shared by the macOS and Windows backends."""

import os
import re
import threading
import time
from urllib.parse import urlparse

import paramiko

# Host keys of the servers added through the dashboard. The API's own ~/.ssh is mounted read-only, so they go here;
# the API image points ssh's GlobalKnownHostsFile at it too, for Docker over SSH.
KNOWN_HOSTS = os.environ.get("ZOO_KNOWN_HOSTS") or (
    "/data/known_hosts" if os.path.isdir("/data") else "data/known_hosts"
)
HOST_KEY = re.compile(
    r"^(ssh-ed25519|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|ssh-rsa) [A-Za-z0-9+/=]+$"
)
known_lock = threading.Lock()


def trust(hostname: str, port: int, host_key: str):
    """Records a server's SSH host key, as the node installer printed it, so connections to it are verified."""
    key = " ".join(host_key.split()[:2])
    if not HOST_KEY.match(key):
        raise ValueError("not an SSH host key")
    line = f"{hostname if port == 22 else f'[{hostname}]:{port}'} {key}"
    with known_lock:
        os.makedirs(os.path.dirname(KNOWN_HOSTS) or ".", exist_ok=True)
        with open(KNOWN_HOSTS, "a+") as f:
            f.seek(0)
            if line not in f.read().splitlines():
                f.write(line + "\n")


def load_known_hosts(client: paramiko.SSHClient):
    client.load_system_host_keys()
    if os.path.exists(KNOWN_HOSTS):
        client.get_host_keys().load(KNOWN_HOSTS)


def open_client(server_id: str, url: str) -> paramiko.SSHClient:
    """Connects to a host's SSH server: through its zoo-node while one is connected, else directly. The host key is
    checked either way, under the URL's host name (a node server's own id for node:// URLs)."""
    from server import nodes

    target = urlparse(url)
    sock = nodes.ssh_socket(server_id)
    if sock is None and target.scheme == "node":
        raise RuntimeError("the server's zoo-node is not connected")
    client = paramiko.SSHClient()
    load_known_hosts(client)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(target.hostname or "", port=target.port or 22, username=target.username, timeout=15, sock=sock)
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(30)
    return client


def alive(client: paramiko.SSHClient | None) -> bool:
    return client is not None and client.get_transport() is not None and client.get_transport().is_active()


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
