import time
import urllib.request

import docker

IMAGE = "zoo-sandbox:latest"

docker_client = docker.from_env()


def run_container(name: str, image: str = IMAGE):
    container = docker_client.containers.run(
        image,
        name=name,
        detach=True,
        mem_limit="2g",
        nano_cpus=2_000_000_000,
        shm_size="1g",
        ports={"6080/tcp": ("127.0.0.1", None)},
    )
    container.reload()
    port_info = container.attrs["NetworkSettings"]["Ports"]["6080/tcp"]
    return container.id, int(port_info[0]["HostPort"])


def wait_for_vnc(host_port: int, timeout: int = 30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{host_port}/vnc.html", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def remove_container(container_id: str):
    try:
        docker_client.containers.get(container_id).remove(force=True)
    except docker.errors.NotFound:
        pass
