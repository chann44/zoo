import os
import shlex
import time
import urllib.request

import docker

IMAGE = "zoo-sandbox:latest"
CODE_IMAGE = os.environ.get("ZOO_CODE_IMAGE", "zoo-code:latest")
HOME = "/home/zoo"
NETWORK = os.environ.get("ZOO_NETWORK")

docker_client = docker.from_env()
remotes: dict[str, docker.DockerClient] = {}
owners: dict[str, docker.DockerClient] = {}


def connect(server_id: str, url: str) -> docker.DockerClient:
    if server_id not in remotes:
        remotes[server_id] = docker.DockerClient(base_url=url, use_ssh_client=url.startswith("ssh://"), timeout=30)
    return remotes[server_id]


def client_for(server) -> docker.DockerClient:
    return docker_client if server is None else connect(server.id, server.docker_url)


def container(container_id: str):
    if container_id in owners:
        return owners[container_id].containers.get(container_id)
    for client in [docker_client, *remotes.values()]:
        try:
            found = client.containers.get(container_id)
        except docker.errors.NotFound:
            continue
        owners[container_id] = client
        return found
    raise docker.errors.NotFound(f"container {container_id} not found")


def ensure_image(client: docker.DockerClient, image: str):
    if client is docker_client:
        return
    try:
        client.images.get(image)
    except docker.errors.ImageNotFound:
        try:
            client.images.pull(image)
        except docker.errors.APIError:
            client.images.load(docker_client.images.get(image).save())


def volume_name(sandbox_id: str) -> str:
    return f"zoo-home-{sandbox_id}"


def run_container(name: str, image: str, sandbox_id: str, env: dict[str, str], server=None, desktop: bool = True):
    client = client_for(server)
    ensure_image(client, image)
    try:
        client.containers.get(name).remove(force=True)
    except docker.errors.NotFound:
        pass
    local = server is None
    bind = "127.0.0.1" if local else server.bind_address
    created = client.containers.run(
        image,
        name=name,
        detach=True,
        environment=env,
        mem_limit="2g",
        nano_cpus=2_000_000_000,
        pids_limit=1024,
        shm_size="1g",
        cap_add=["NET_ADMIN"],
        security_opt=["no-new-privileges"],
        volumes={volume_name(sandbox_id): {"bind": HOME, "mode": "rw"}},
        labels={"zoo.sandbox": sandbox_id},
        network=NETWORK if local else None,
        ports={"6080/tcp": (bind, None)} if desktop and not (local and NETWORK) else None,
    )
    owners[created.id] = client
    if not desktop:
        return created.id, None, None
    if local and NETWORK:
        return created.id, name, 6080
    created.reload()
    port_info = created.attrs["NetworkSettings"]["Ports"]["6080/tcp"]
    return created.id, bind, int(port_info[0]["HostPort"])


def wait_for_vnc(host: str, port: int, timeout: int = 30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://{host}:{port}/vnc.html", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def remove_container(container_id: str):
    try:
        container(container_id).remove(force=True)
    except docker.errors.NotFound:
        pass
    owners.pop(container_id, None)


def remove_volume(sandbox_id: str, server=None):
    try:
        client_for(server).volumes.get(volume_name(sandbox_id)).remove(force=True)
    except docker.errors.NotFound:
        pass


def copy_volume(sandbox_id: str, source, target, image: str = IMAGE):
    src, dst = client_for(source), client_for(target)
    ensure_image(dst, image)
    volumes = {volume_name(sandbox_id): {"bind": HOME, "mode": "rw"}}
    reader = src.containers.create(image, volumes=volumes, entrypoint=["true"])
    writer = dst.containers.create(image, volumes=volumes, entrypoint=["true"])
    try:
        stream, _ = reader.get_archive(HOME)
        if not writer.put_archive("/home", b"".join(stream)):
            raise RuntimeError("copy failed")
    finally:
        reader.remove(force=True)
        writer.remove(force=True)
    remove_volume(sandbox_id, source)


def export_dir(container_id: str, path: str) -> bytes:
    stream, _ = container(container_id).get_archive(path)
    return b"".join(stream)


def import_dir(container_id: str, parent: str, data: bytes):
    root_exec(container_id, f"mkdir -p {shlex.quote(parent)} && chown zoo:zoo {shlex.quote(parent)}")
    if not container(container_id).put_archive(parent, data):
        raise RuntimeError("import failed")
    root_exec(container_id, f"chown -R zoo:zoo {shlex.quote(parent)}")


def is_running(container_id: str) -> bool:
    try:
        return container(container_id).status == "running"
    except docker.errors.NotFound:
        return False


def root_exec(container_id: str, script: str):
    result = container(container_id).exec_run(["sh", "-c", script], user="root")
    if result.exit_code != 0:
        raise RuntimeError(result.output.decode(errors="replace"))
    return result.output.decode(errors="replace")


def apply_network(container_id: str, default_action: str, allow_dns: bool, rules: list[tuple[str, str, str]]):
    lines = ["set -e", "iptables -F OUTPUT"]
    if not allow_dns:
        lines.append("iptables -A OUTPUT -d 127.0.0.11 -j REJECT")
    lines += [
        "iptables -A OUTPUT -o lo -j ACCEPT",
        "iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
    ]
    if allow_dns:
        lines += ["iptables -A OUTPUT -p udp --dport 53 -j ACCEPT", "iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT"]
    for rule_type, value, effect in rules:
        target = "ACCEPT" if effect == "allow" else "REJECT"
        if rule_type == "domain":
            lines.append(
                f"for ip in $(getent ahostsv4 {shlex.quote(value)} | awk '{{print $1}}' | sort -u); do "
                f"iptables -A OUTPUT -d $ip -j {target}; done"
            )
        else:
            lines.append(f"iptables -A OUTPUT -d {shlex.quote(value)} -j {target}")
    if default_action == "deny":
        lines.append("iptables -A OUTPUT -j REJECT")
    root_exec(container_id, "\n".join(lines))


def apply_apps(container_id: str, effects: dict[str, str]):
    lines = []
    for binary, effect in effects.items():
        mode = "755" if effect == "allow" else "700"
        lines.append(f"p=$(command -v {shlex.quote(binary)}) && chmod {mode} $(readlink -f $p) || true")
    if lines:
        root_exec(container_id, "\n".join(lines))


def export_home(container_id: str):
    stream, _ = container(container_id).get_archive(HOME)
    return stream


def import_home(container_id: str, data: bytes):
    if not container(container_id).put_archive("/home", data):
        raise RuntimeError("restore failed")
    root_exec(container_id, f"chown -R zoo:zoo {HOME}")
