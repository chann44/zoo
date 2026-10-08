import io
import json
import tarfile

import pytest

from db.connection import db_manager
from server import pool
from tests.conftest import present
from tests.test_sandboxes import add_server


@pytest.fixture
def warm(zoo, monkeypatch):
    """A pool that boots in the calling thread, with guests that connect at once."""
    monkeypatch.setattr(pool, "guest_ready", lambda server: True)
    monkeypatch.setattr(pool.hub, "wait_for_guest", lambda sandbox_id, timeout=30: True)
    zoo.sandbox_api.pool.inline = True
    zoo.sandbox_api.pool.claimed.clear()
    yield zoo.sandbox_api.pool
    zoo.sandbox_api.pool.inline = False


def rows():
    with db_manager.session() as db:
        return list(db.list_pool_sandboxes())


def test_only_admins_size_the_local_pool(client, alice, admin):
    assert client.put("/pool", json={"kind": "desktop", "size": 1}, headers=alice).status_code == 403
    assert client.get("/pool", headers=alice).json() == []
    res = client.put("/pool", json={"kind": "desktop", "size": 2}, headers=admin)
    assert res.status_code == 200, res.text
    assert res.json()["size"] == 2 and res.json()["server_name"] == "This machine"
    assert client.put("/pool", json={"kind": "desktop", "size": 99}, headers=admin).status_code == 422


def test_owners_size_their_servers_pool(client, alice, bob):
    box = add_server("alice@example.com")
    assert client.put("/pool", json={"kind": "code", "server_id": box, "size": 1}, headers=bob).status_code == 404
    assert client.put("/pool", json={"kind": "code", "server_id": box, "size": 1}, headers=alice).status_code == 200
    entries = client.get("/pool", headers=alice).json()
    assert {(e["kind"], e["size"]) for e in entries} == {("desktop", 0), ("browser", 0), ("code", 1)}


def test_create_claims_a_warm_sandbox(client, admin, alice, warm, fake):
    client.put("/pool", json={"kind": "desktop", "size": 1}, headers=admin)
    warm.fill()
    [pooled] = rows()
    assert pooled.status == "idle"
    container = fake.containers[pooled.runtime_id]
    assert "ZOO_VNC_PASSWORD" in container.env and container.sandbox_id == pooled.id

    [secret] = client.post("/vault/secrets", json={"name": "API_KEY", "value": "sk-warm-123456"}, headers=alice).json()
    res = client.post("/sandboxes", json={"kind": "desktop", "secret_ids": [secret["id"]]}, headers=alice)
    sandbox = client.get(f"/sandboxes/{res.json()['id']}", headers=alice).json()
    assert sandbox["id"] == pooled.id and sandbox["status"] == "running"
    with db_manager.session() as db:
        stored = present(db.get_sandbox(id=pooled.id))
    assert stored.runtime_id == pooled.runtime_id
    # the pooled container's VNC password carries over, and the secrets reach the guest's file, not the env
    assert json.loads(stored.config)["vnc_password"] == json.loads(pooled.config)["vnc_password"]
    assert "API_KEY" not in container.env
    with tarfile.open(fileobj=io.BytesIO(container.dirs["/run/zoo"])) as tar:
        member = tar.getmember("env.json")
        assert member.mode == 0o600
        assert json.load(present(tar.extractfile(member))) == {"API_KEY": "sk-warm-123456"}
    assert client.get("/pool", headers=admin).json()[0]["claimed"] == 1

    # the next fill boots a replacement
    assert rows() == []
    warm.fill()
    assert [r.status for r in rows()] == ["idle"]


def test_cold_boot_without_a_pool(client, alice, warm, fake):
    sandbox = client.post("/sandboxes", json={"kind": "code"}, headers=alice).json()
    with db_manager.session() as db:
        assert "pooled" not in json.loads(present(db.get_sandbox(id=sandbox["id"])).config)


def test_lost_pooled_container_falls_back_to_a_cold_boot(client, admin, alice, warm, fake):
    client.put("/pool", json={"kind": "code", "size": 1}, headers=admin)
    warm.fill()
    [pooled] = rows()
    fake.containers[pooled.runtime_id].running = False
    sandbox = client.post("/sandboxes", json={"kind": "code"}, headers=alice).json()
    sandbox = client.get(f"/sandboxes/{sandbox['id']}", headers=alice).json()
    assert sandbox["status"] == "running"
    with db_manager.session() as db:
        assert present(db.get_sandbox(id=pooled.id)).runtime_id != pooled.runtime_id


def test_shrinking_and_stale_images_drain_the_pool(client, admin, warm, fake, monkeypatch):
    client.put("/pool", json={"kind": "code", "size": 2}, headers=admin)
    warm.fill()
    assert len(rows()) == 2
    client.put("/pool", json={"kind": "code", "size": 1}, headers=admin)
    warm.fill()
    assert len(rows()) == 1
    monkeypatch.setattr("server.docker.CODE_IMAGE", "zoo-code:next")
    warm.fill()
    [fresh] = rows()
    assert fresh.image == "zoo-code:next"
    assert len(fake.containers) == 1


def test_a_failed_boot_holds_the_pool_back(client, admin, warm, fake):
    fake.fail_boot = "image pull failed"
    client.put("/pool", json={"kind": "code", "size": 2}, headers=admin)
    warm.fill()
    assert [r.status for r in rows()] == ["failed", "failed"]
    fake.fail_boot = None
    warm.fill()
    assert [r.status for r in rows()] == ["failed", "failed"]
    entry = next(e for e in client.get("/pool", headers=admin).json() if e["kind"] == "code")
    assert entry["error"] == "image pull failed" and entry["idle"] == 0
