import os
import shlex
import time
import urllib.parse
import urllib.request

import docker

IMAGE = os.environ.get("ZOO_SANDBOX_IMAGE", "zoo-sandbox:latest")
CODE_IMAGE = os.environ.get("ZOO_CODE_IMAGE", "zoo-code:latest")
HOME = "/home/zoo"
NETWORK = os.environ.get("ZOO_NETWORK")
RUNTIME = os.environ.get("ZOO_RUNTIME", "kata")

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


def prepull(server):
    """Pulls every sandbox image onto a server, so the first boot after a release or on a new server doesn't wait
    on a multi-GB pull."""
    client = connect(server.id, server.docker_url)
    for image in (IMAGE, CODE_IMAGE):
        ensure_image(client, image)


def runtime_for(client: docker.DockerClient) -> str:
    info = client.info()
    if RUNTIME in info.get("Runtimes", {}):
        return RUNTIME
    if "Docker Desktop" in (info.get("OperatingSystem") or ""):
        # on a Mac or Windows host, Docker Desktop already runs every container inside its own Linux VM
        return "runc"
    raise RuntimeError(
        f"docker runtime '{RUNTIME}' is not configured on this host; install Kata Containers and register it "
        f"in /etc/docker/daemon.json (see README), or set ZOO_RUNTIME=runc to run plain containers"
    )


def volume_name(sandbox_id: str) -> str:
    return f"zoo-home-{sandbox_id}"


def adoptable(client: docker.DockerClient, name: str, image: str, sandbox_id: str):
    """The sandbox's container left running by an earlier attempt, so a retried boot reuses it; anything else under
    that name is removed."""
    try:
        existing = client.containers.get(name)
    except docker.errors.NotFound:
        return None
    if (
        existing.status == "running"
        and existing.labels.get("zoo.sandbox") == sandbox_id
        and existing.attrs["Config"]["Image"] == image
    ):
        return existing
    existing.remove(force=True)
    return None


TUNNEL_LABEL = "zoo.guest.tunnel"


def run_container(name: str, image: str, sandbox_id: str, env: dict[str, str], server=None, desktop: bool = True):
    client = client_for(server)
    runtime = runtime_for(client)
    ensure_image(client, image)
    local = server is None
    bind = "127.0.0.1" if local else server.bind_address
    # images labelled zoo.guest.tunnel serve their desktop through the guest, so 6080 stays unpublished
    tunnel = desktop and "ZOO_GUEST_TOKEN" in env and TUNNEL_LABEL in (client.images.get(image).labels or {})
    created = adoptable(client, name, image, sandbox_id)
    if created is None:
        created = client.containers.run(
            image,
            name=name,
            detach=True,
            runtime=runtime,
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
            ports={"6080/tcp": (bind, None)} if desktop and not tunnel and not (local and NETWORK) else None,
        )
    owners[created.id] = client
    if not desktop:
        return created.id, None, None
    if tunnel:
        # no port: the desktop is reached through the guest
        return created.id, name if local and NETWORK else bind, None
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


def guest_endpoint(container_id: str) -> tuple[str, int] | None:
    env = dict(e.split("=", 1) for e in container(container_id).attrs["Config"].get("Env") or [] if "=" in e)
    url = urllib.parse.urlsplit(env.get("ZOO_GUEST_URL", ""))
    if not url.hostname:
        return None
    return url.hostname, url.port or (443 if url.scheme == "wss" else 80)


def apply_network(container_id: str, default_action: str, allow_dns: bool, rules: list[tuple[str, str, str]]):
    if root_exec(container_id, "command -v iptables || true").strip() == "":
        raise RuntimeError("sandbox runs an outdated image without iptables; stop and start it to upgrade")
    lines = ["set -e", "iptables -F OUTPUT"]
    endpoint = guest_endpoint(container_id)
    if endpoint is not None:
        # the in-sandbox guest must always reach the API, whatever the policy; resolved before DNS can be blocked
        host, port = endpoint
        lines.append(
            f"for ip in $(getent ahostsv4 {shlex.quote(host)} | awk '{{print $1}}' | sort -u); do "
            f"iptables -A OUTPUT -d $ip -p tcp --dport {port} -j ACCEPT; done"
        )
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
