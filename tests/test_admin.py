import pytest

from server import admin_api
from tests.conftest import POSTGRES


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    monkeypatch.setattr(admin_api, "resolve", lambda hostname: ["203.0.113.7"])


def test_admin_routes_need_an_admin(client, alice):
    for method, path in [
        ("get", "/admin/users"),
        ("get", "/admin/sandboxes"),
        ("get", "/admin/domains"),
        ("post", "/admin/backups"),
        ("get", "/admin/backups"),
    ]:
        assert client.request(method, path, headers=alice).status_code == 403, path
    assert client.post("/admin/domains", json={"hostname": "zoo.example.com"}, headers=alice).status_code == 403


def test_admin_sees_all_users_and_sandboxes(client, admin, alice, make_sandbox):
    make_sandbox()
    assert {u["email"] for u in client.get("/admin/users", headers=admin).json()} == {
        "admin@example.com",
        "alice@example.com",
    }
    assert len(client.get("/admin/sandboxes", headers=admin).json()) == 1


def test_domains(client, admin):
    res = client.post("/admin/domains", json={"hostname": "zoo.example.com"}, headers=admin)
    assert res.status_code == 201
    domain = res.json()
    assert domain["url"] == "https://zoo.example.com"
    assert domain["addresses"] == ["203.0.113.7"]
    assert client.post("/admin/domains", json={"hostname": "zoo.example.com"}, headers=admin).status_code == 409
    assert client.post("/admin/domains", json={"hostname": "Not A Host"}, headers=admin).status_code == 422

    assert client.get("/domains/check", params={"domain": "zoo.example.com"}).json() == {"ok": True}
    assert client.get("/domains/check", params={"domain": "evil.example.com"}).status_code == 404

    assert client.delete(f"/admin/domains/{domain['id']}", headers=admin).status_code == 204
    assert client.get("/admin/domains", headers=admin).json() == []
    assert client.get("/domains/check", params={"domain": "zoo.example.com"}).status_code == 404


def test_backups(client, admin):
    if POSTGRES:
        # the database's own backups cover Postgres
        assert client.post("/admin/backups", headers=admin).status_code == 409
        return
    created = client.post("/admin/backups", headers=admin)
    assert created.status_code == 201
    assert created.json()["name"].startswith("zoo-") and created.json()["size"] > 0
    assert created.json()["name"] in [b["name"] for b in client.get("/admin/backups", headers=admin).json()]
