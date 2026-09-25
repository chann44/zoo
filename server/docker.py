import os
import shlex
import time
import urllib.request

import docker

IMAGE = "zoo-sandbox:latest"
HOME = "/home/zoo"
NETWORK = os.environ.get("ZOO_NETWORK")

docker_client = docker.from_env()


def volume_name(sandbox_id: str) -> str:
    return f"zoo-home-{sandbox_id}"


def run_container(name: str, image: str, sandbox_id: str, env: dict[str, str]):
    try:
        docker_client.containers.get(name).remove(force=True)
    except docker.errors.NotFound:
        pass
    container = docker_client.containers.run(
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
        network=NETWORK,
        ports=None if NETWORK else {"6080/tcp": ("127.0.0.1", None)},
    )
    container.reload()
    if NETWORK:
        return container.id, name, 6080
    port_info = container.attrs["NetworkSettings"]["Ports"]["6080/tcp"]
    return container.id, "127.0.0.1", int(port_info[0]["HostPort"])


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
        docker_client.containers.get(container_id).remove(force=True)
    except docker.errors.NotFound:
        pass


def remove_volume(sandbox_id: str):
    try:
        docker_client.volumes.get(volume_name(sandbox_id)).remove(force=True)
    except docker.errors.NotFound:
        pass


def is_running(container_id: str) -> bool:
    try:
        return docker_client.containers.get(container_id).status == "running"
    except docker.errors.NotFound:
        return False


def root_exec(container_id: str, script: str):
    result = docker_client.containers.get(container_id).exec_run(["sh", "-c", script], user="root")
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
    stream, _ = docker_client.containers.get(container_id).get_archive(HOME)
    return stream


def import_home(container_id: str, data: bytes):
    container = docker_client.containers.get(container_id)
    if not container.put_archive("/home", data):
        raise RuntimeError("restore failed")
    root_exec(container_id, f"chown -R zoo:zoo {HOME}")
