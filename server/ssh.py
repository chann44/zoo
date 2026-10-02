"""SSH command execution shared by the macOS and Windows backends."""

import time

import paramiko


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
