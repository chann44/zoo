"""Routes sandbox runtime operations to Docker (Linux sandboxes) or zoovm (macOS microVMs)."""

from server import docker, macos


def backend(runtime_id: str):
    return macos if macos.is_vm(runtime_id) else docker


def remove_container(runtime_id: str):
    if macos.is_vm(runtime_id):
        macos.stop(runtime_id)
    else:
        docker.remove_container(runtime_id)


def remove_volume(sandbox, server):
    if sandbox.kind == "macos":
        if server is not None:
            macos.delete(sandbox.id, server)
    else:
        docker.remove_volume(sandbox.id, server)


def is_running(runtime_id: str) -> bool:
    return backend(runtime_id).is_running(runtime_id)


def export_dir(runtime_id: str, path: str) -> bytes:
    return backend(runtime_id).export_dir(runtime_id, path)


def import_dir(runtime_id: str, parent: str, data: bytes):
    backend(runtime_id).import_dir(runtime_id, parent, data)


def export_home(runtime_id: str):
    return backend(runtime_id).export_home(runtime_id)


def import_home(runtime_id: str, data: bytes):
    backend(runtime_id).import_home(runtime_id, data)


def apply_network(runtime_id: str, default_action: str, allow_dns: bool, rules: list[tuple[str, str, str]]):
    backend(runtime_id).apply_network(runtime_id, default_action, allow_dns, rules)


def apply_apps(runtime_id: str, effects: dict[str, str]):
    backend(runtime_id).apply_apps(runtime_id, effects)


def connect(server):
    if server.platform == "macos":
        return macos.connect(server.id, server.docker_url)
    return docker.connect(server.id, server.docker_url)
