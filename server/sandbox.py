import docker
import uuid

IMAGE = "zoo-sandbox:latest"

docker_client = docker.from_env()


sandboxes = {}


def create_sandbox():
    sandbox_id = str(uuid.uuid4())

    container_name = f"zoo-sandbox-{sandbox_id}"

    container = docker_client.containers.run(
        IMAGE,
        name=container_name,
        detach=True,
        mem_limit="2g",
        nano_cpus=2_000_000_000,
        ports={
            "6080/tcp": ("127.0.0.1", None),
        },
    )
    container.reload()
    port_info = container.attrs["NetworkSettings"]["Ports"]["6080/tcp"]
    host_port = int(port_info[0]["HostPort"])
    sandbox = {
        "id": sandbox_id,
        "container_id": container.id,
        "container_name": container_name,
        "host_port": host_port,
    }

    sandboxes[sandbox_id] = sandbox
    return sandbox


def get_sandbox(sandbox_id):
    return sandboxes[sandbox_id]


def delete_sandbox(sandbox_id):

    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        return None
    try:
        container = docker_client.containers.get(sandboxes["container_id"])

        container.remove(force=True)
    except docker.errors.NotFound:
        pass

    del sandboxes[sandbox_id]

    return True
