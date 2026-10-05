import os

from server.sandbox_api import PROFILE_DIR
from server.security import decrypt_bytes
from tests.conftest import runtime_of


def capture(client, headers, fake, sandbox, name="work login", data=b"firefox-profile-tar"):
    fake.containers[runtime_of(sandbox["id"])].dirs["/home/zoo/.mozilla"] = data
    res = client.post(f"/sandboxes/{sandbox['id']}/profiles", json={"name": name, "app": "firefox"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_capture_stores_an_encrypted_profile(client, alice, sandbox, fake):
    profile = capture(client, alice, fake, sandbox)
    assert profile["name"] == "work login" and profile["app"] == "firefox"
    path = os.path.join(PROFILE_DIR, f"{profile['id']}.tar")
    with open(path, "rb") as f:
        stored = f.read()
    assert stored != b"firefox-profile-tar"
    assert decrypt_bytes(stored) == b"firefox-profile-tar"
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert [p["id"] for p in client.get("/profiles", headers=alice).json()] == [profile["id"]]


def test_capture_errors(client, alice, sandbox):
    sid = sandbox["id"]
    assert client.post(f"/sandboxes/{sid}/profiles", json={"name": "x", "app": "netscape"}, headers=alice).status_code == 422
    assert client.post(f"/sandboxes/{sid}/profiles", json={"name": "x", "app": "firefox"}, headers=alice).status_code == 404


def test_apply_to_running_sandbox_and_at_create(client, alice, sandbox, make_sandbox, fake):
    profile = capture(client, alice, fake, sandbox)
    other = make_sandbox()
    res = client.post(f"/sandboxes/{other['id']}/profiles/{profile['id']}", headers=alice)
    assert res.status_code == 200
    assert fake.containers[runtime_of(other["id"])].dirs == {"/home/zoo": b"firefox-profile-tar"}

    fresh = make_sandbox(profile_ids=[profile["id"]])
    assert fake.containers[runtime_of(fresh["id"])].dirs == {"/home/zoo": b"firefox-profile-tar"}


def test_rename_and_delete(client, alice, sandbox, fake):
    profile = capture(client, alice, fake, sandbox)
    renamed = client.patch(f"/profiles/{profile['id']}", json={"name": "  personal "}, headers=alice).json()
    assert renamed["name"] == "personal"
    assert client.delete(f"/profiles/{profile['id']}", headers=alice).status_code == 204
    assert not os.path.exists(os.path.join(PROFILE_DIR, f"{profile['id']}.tar"))
    assert client.get("/profiles", headers=alice).json() == []


def test_profiles_are_private(client, alice, bob, sandbox, make_sandbox, fake):
    profile = capture(client, alice, fake, sandbox)
    bobs = make_sandbox(headers=bob)
    assert client.get("/profiles", headers=bob).json() == []
    assert client.post(f"/sandboxes/{bobs['id']}/profiles/{profile['id']}", headers=bob).status_code == 404
    assert client.patch(f"/profiles/{profile['id']}", json={"name": "mine"}, headers=bob).status_code == 404
    assert client.delete(f"/profiles/{profile['id']}", headers=bob).status_code == 404
    assert client.post("/sandboxes", json={"profile_ids": [profile["id"]]}, headers=bob).status_code == 404
