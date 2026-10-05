from tests.conftest import runtime_of


def secrets_env(env: dict[str, str]) -> dict[str, str]:
    """The container env without the x11vnc password every desktop sandbox gets."""
    return {k: v for k, v in env.items() if k != "ZOO_VNC_PASSWORD"}


def create(client, headers, name="GITHUB_TOKEN", value="ghp_abcdef123456", **extra):
    res = client.post("/vault/secrets", json={"name": name, "value": value, **extra}, headers=headers)
    assert res.status_code == 201, res.text
    return next(s for s in res.json() if s["name"] == name)


def test_vault_crud_never_returns_values(client, alice):
    secret = create(client, alice, description="  ci token ")
    assert secret["description"] == "ci token"
    assert "value" not in secret and "ciphertext" not in secret
    assert client.post("/vault/secrets", json={"name": "GITHUB_TOKEN", "value": "x"}, headers=alice).status_code == 409

    [updated] = client.patch(
        f"/vault/secrets/{secret['id']}", json={"value": "ghp_rotated99", "description": "rotated"}, headers=alice
    ).json()
    assert updated["description"] == "rotated"
    assert client.delete(f"/vault/secrets/{secret['id']}", headers=alice).json() == []


def test_vault_secret_is_injected_when_attached(client, alice, make_sandbox, fake):
    secret = create(client, alice)
    sandbox = make_sandbox(secret_ids=[secret["id"]])
    assert secrets_env(fake.containers[runtime_of(sandbox["id"])].env) == {"GITHUB_TOKEN": "ghp_abcdef123456"}
    assert client.get(f"/sandboxes/{sandbox['id']}/vault-secrets", headers=alice).json() == [
        {"id": secret["id"], "name": "GITHUB_TOKEN"}
    ]
    [listed] = client.get("/vault/secrets", headers=alice).json()
    assert listed["sandboxes"] == [{"id": sandbox["id"], "name": sandbox["name"]}]
    assert listed["last_used_at"] is not None


def test_attach_and_detach(client, alice, sandbox, fake):
    sid = sandbox["id"]
    secret = create(client, alice)
    assert client.put(f"/sandboxes/{sid}/vault-secrets/{secret['id']}", headers=alice).json() == [
        {"id": secret["id"], "name": "GITHUB_TOKEN"}
    ]
    out = client.post(f"/sandboxes/{sid}/exec", json={"command": "echo ghp_abcdef123456"}, headers=alice).json()
    assert out["stdout"] == "echo [redacted]"
    assert client.delete(f"/sandboxes/{sid}/vault-secrets/{secret['id']}", headers=alice).json() == []


def test_sandbox_secret_wins_over_vault_secret(client, alice, make_sandbox, fake):
    secret = create(client, alice, name="TOKEN", value="from-vault")
    sandbox = make_sandbox(secret_ids=[secret["id"]])
    sid = sandbox["id"]
    client.put(f"/sandboxes/{sid}/secrets", json={"name": "TOKEN", "value": "from-sandbox"}, headers=alice)
    client.post(f"/sandboxes/{sid}/stop", headers=alice)
    client.post(f"/sandboxes/{sid}/start", headers=alice)
    assert secrets_env(fake.containers[runtime_of(sid)].env) == {"TOKEN": "from-sandbox"}


def test_activity_log(client, alice, sandbox):
    secret = create(client, alice)
    client.patch(f"/vault/secrets/{secret['id']}", json={"value": "ghp_new_value"}, headers=alice)
    client.put(f"/sandboxes/{sandbox['id']}/vault-secrets/{secret['id']}", headers=alice)
    client.delete(f"/vault/secrets/{secret['id']}", headers=alice)
    actions = [a["action"] for a in client.get("/vault/activity", headers=alice).json()]
    assert sorted(actions) == sorted(["secret.create", "secret.rotate", "secret.attach", "secret.delete"])
    assert all("ghp_" not in str(a["metadata"]) for a in client.get("/vault/activity", headers=alice).json())


def test_vault_is_private(client, alice, bob, sandbox, make_sandbox):
    secret = create(client, alice)
    assert client.get("/vault/secrets", headers=bob).json() == []
    assert client.patch(f"/vault/secrets/{secret['id']}", json={"value": "stolen"}, headers=bob).status_code == 404
    assert client.delete(f"/vault/secrets/{secret['id']}", headers=bob).status_code == 404
    assert client.post("/sandboxes", json={"secret_ids": [secret["id"]]}, headers=bob).status_code == 404
    bobs = make_sandbox(headers=bob)
    assert client.put(f"/sandboxes/{bobs['id']}/vault-secrets/{secret['id']}", headers=bob).status_code == 404
    assert client.get("/vault/activity", headers=bob).json() == []
