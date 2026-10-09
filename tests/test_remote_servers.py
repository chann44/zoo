"""Remote Linux servers reached with Docker over SSH (ssh://user@host), the transport until zoo-node replaces it."""

from types import SimpleNamespace
from typing import ClassVar

import pytest

from server import docker
from tests.conftest import runtime_of
from tests.test_sandboxes import add_server


class Client:
    """A docker.DockerClient that records how it was made and holds some containers."""

    made: ClassVar[list[tuple]] = []

    def __init__(self, base_url, use_ssh_client=False, timeout=None):
        Client.made.append((base_url, use_ssh_client, timeout))
        self.base_url = base_url
        self.held: dict[str, object] = {}
        self.containers = SimpleNamespace(get=self.get)

    def get(self, container_id):
        if container_id not in self.held:
            raise docker.docker.errors.NotFound(container_id)
        return self.held[container_id]


@pytest.fixture
def clients(monkeypatch):
    Client.made = []
    monkeypatch.setattr(docker.docker, "DockerClient", Client)
    monkeypatch.setattr(docker, "remotes", {})
    return Client


def test_ssh_urls_use_the_ssh_client_and_connect_once(fake, clients):
    connect = fake.originals["connect"]
    box = connect("box", "ssh://zoo@box.internal")
    assert connect("box", "ssh://zoo@box.internal") is box
    connect("tls", "tcp://10.0.0.3:2376")
    assert clients.made == [("ssh://zoo@box.internal", True, 30), ("tcp://10.0.0.3:2376", False, 30)]


def test_a_sandbox_placed_on_a_remote_server_runs_there(client, alice, fake):
    server_id = add_server("alice@example.com")
    res = client.post("/sandboxes", json={"kind": "desktop", "server_id": server_id}, headers=alice)
    assert res.status_code == 201
    sandbox = client.get(f"/sandboxes/{res.json()['id']}", headers=alice).json()
    assert sandbox["status"] == "running"
    assert fake.containers[runtime_of(sandbox["id"])].server_id == server_id


def test_remote_servers_are_registered_by_ssh_url(client, admin, fake, monkeypatch):
    reached = []

    class Remote:
        def info(self):
            return {"Name": "box", "OperatingSystem": "Ubuntu 24.04", "NCPU": 8, "Runtimes": {docker.RUNTIME: {}}}

    def connect(server_id, url):
        reached.append(url)
        return Remote()

    monkeypatch.setattr("server.servers_api.connect", connect)
    res = client.post(
        "/servers",
        json={"name": "box", "docker_url": "ssh://zoo@10.0.0.2", "bind_address": "10.0.0.2", "platform": "linux"},
        headers=admin,
    )
    assert res.status_code == 201, res.text
    assert res.json()["docker_url"] == "ssh://zoo@10.0.0.2"
    assert res.json()["capabilities"] == ["linux"]
    assert reached == ["ssh://zoo@10.0.0.2"]
    status = client.get(f"/servers/{res.json()['id']}/status", headers=admin).json()
    assert status["online"] is True and status["os"] == "Ubuntu 24.04"
    bad = client.post(
        "/servers", json={"name": "x", "docker_url": "http://10.0.0.2", "bind_address": "10.0.0.2"}, headers=admin
    )
    assert bad.status_code == 422
