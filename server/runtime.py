"""Routes sandbox runtime operations to Docker (Linux sandboxes), zoovm (macOS microVMs) or Hyper-V (Windows VMs)."""

from server import docker, macos, windows

VMS = {"macos": macos, "windows": windows}


def backend(runtime_id: str):
    if macos.is_vm(runtime_id):
        return macos
    if windows.is_vm(runtime_id):
        return windows
    return docker


def is_vm(runtime_id: str | None) -> bool:
    return macos.is_vm(runtime_id) or windows.is_vm(runtime_id)


def remove_container(runtime_id: str):
    if is_vm(runtime_id):
        backend(runtime_id).stop(runtime_id)
    else:
        docker.remove_container(runtime_id)


def remove_volume(sandbox, server):
    if sandbox.kind in VMS:
        if server is not None:
            VMS[sandbox.kind].delete(sandbox.id, server)
    else:
        docker.remove_volume(sandbox.id, server)


def is_running(runtime_id: str) -> bool:
    return backend(runtime_id).is_running(runtime_id)


def export_dir(runtime_id: str, path: str) -> bytes:
    return backend(runtime_id).export_dir(runtime_id, path)


def import_dir(runtime_id: str, parent: str, data: bytes):
    backend(runtime_id).import_dir(runtime_id, parent, data)


def app_running(runtime_id: str, app: str) -> bool:
    """Whether a profile app (PROFILE_APPS) is running in the sandbox."""
    return backend(runtime_id).app_running(runtime_id, app)


def export_home(runtime_id: str):
    return backend(runtime_id).export_home(runtime_id)


def import_home(runtime_id: str, data: bytes):
    backend(runtime_id).import_home(runtime_id, data)


def apply_network(runtime_id: str, default_action: str, allow_dns: bool, rules: list[tuple[str, str, str]]):
    backend(runtime_id).apply_network(runtime_id, default_action, allow_dns, rules)


def apply_apps(runtime_id: str, effects: dict[str, str]):
    backend(runtime_id).apply_apps(runtime_id, effects)


def vnc(runtime_id: str):
    """A connected VNC client for a macOS or Windows VM, as a context manager."""
    return backend(runtime_id).vnc(runtime_id)


def authenticated_channel(runtime_id: str):
    return backend(runtime_id).authenticated_channel(runtime_id)


def connect(server):
    if server.platform in VMS:
        return VMS[server.platform].connect(server.id, server.docker_url)
    return docker.connect(server.id, server.docker_url)


def ping(server):
    """Raises unless the server answers: a Docker ping, or an open SSH connection for macOS and Windows hosts."""
    client = connect(server)
    if server.platform not in VMS:
        client.ping()
