import uuid
from dataclasses import dataclass, field

import docker


@dataclass
class Computer:
    name: str
    address: str
    ssh_user: str
    ssh_port: int = 22
    ssh_key_path: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


_computers: dict[str, Computer] = {}
_clients: dict[str, docker.DockerClient] = {}


def register_computer(
    name: str,
    address: str,
    ssh_user: str,
    ssh_port: int = 22,
    ssh_key_path: str | None = None,
) -> Computer:
    computer = Computer(
        name=name,
        address=address,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_key_path=ssh_key_path,
    )
    _computers[computer.id] = computer
    return computer


def get_computer(computer_id: str) -> Computer | None:
    return _computers.get(computer_id)


def list_computers() -> list[Computer]:
    return list(_computers.values())


def remove_computer(computer_id: str) -> bool:
    _clients.pop(computer_id, None)
    return _computers.pop(computer_id, None) is not None


def _base_url(computer: Computer) -> str:
    url = f"ssh://{computer.ssh_user}@{computer.address}:{computer.ssh_port}"
    return url


def get_docker_client(computer: Computer | None = None) -> docker.DockerClient:

    if computer is None:
        return docker.from_env()

    client = _clients.get(computer.id)
    if client is not None:
        return client

    use_ssh_client = docker.constants.IS_WINDOWS_PLATFORM is False

    client = docker.DockerClient(
        base_url=_base_url(computer),
        use_ssh_client=use_ssh_client,
    )
    _clients[computer.id] = client
    return client


def test_connection(computer: Computer) -> tuple[bool, str | None]:
    try:
        client = get_docker_client(computer)
        client.ping()
        return True, None
    except Exception as exc:
        _clients.pop(computer.id, None)
        return False, str(exc)


IMAGE = "zoo-sandbox:latest"


def deploy_sandbox(
    computer: Computer | None = None,
    image: str = IMAGE,
    mem_limit: str = "2g",
    nano_cpus: int = 2_000_000_000,
) -> dict:
    

    client = get_docker_client(computer)

    sandbox_id = str(uuid.uuid4())
    container_name = f"zoo-sandbox-{sandbox_id}"
   
    bind_host = "127.0.0.1" if computer is None else "0.0.0.0"

    container = client.containers.run(
        image,
        name=container_name,
        detach=True,
        mem_limit=mem_limit,
        nano_cpus=nano_cpus,
        ports={"6080/tcp": (bind_host, None)},
    )
    container.reload()

    port_info = container.attrs["NetworkSettings"]["Ports"]["6080/tcp"]
    host_port = int(port_info[0]["HostPort"])
    host_address = "127.0.0.1" if computer is None else computer.address

    return {
        "id": sandbox_id,
        "computer_id": computer.id if computer else None,
        "container_id": container.id,
        "container_name": container_name,
        "host_address": host_address,
        "host_port": host_port,
    }
