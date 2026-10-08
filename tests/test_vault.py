import io
import json
import tarfile
from datetime import UTC, datetime, timedelta

from server import vault_api
from tests.conftest import present, runtime_of, sql


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
    [usage] = listed["sandboxes"]
    assert usage["id"] == sandbox["id"] and usage["name"] == sandbox["name"] and usage["status"] == "running"
    assert usage["last_used_at"] is not None
    assert listed["last_used_at"] is not None
    assert listed["status"] == "ok" and listed["used_by_agent"] is False


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


def pushed(fake, sandbox_id: str) -> tuple[dict, list]:
    """The secrets last pushed into a running Linux sandbox: env.json and unset.json under /run/zoo."""
    with tarfile.open(fileobj=io.BytesIO(fake.containers[runtime_of(sandbox_id)].dirs["/run/zoo"])) as tar:
        files = {m.name: json.loads(present(tar.extractfile(m)).read()) for m in tar.getmembers()}
    return files["env.json"], files["unset.json"]


def test_changes_reach_a_running_sandbox_without_a_restart(client, alice, make_sandbox, fake):
    secret = create(client, alice)
    sandbox = make_sandbox(secret_ids=[secret["id"]])
    sid = sandbox["id"]
    runtime = runtime_of(sid)

    client.patch(f"/vault/secrets/{secret['id']}", json={"value": "ghp_rotated"}, headers=alice)
    assert pushed(fake, sid) == ({"GITHUB_TOKEN": "ghp_rotated"}, [])

    other = create(client, alice, name="NPM_TOKEN", value="npm_123456")
    client.put(f"/sandboxes/{sid}/vault-secrets/{other['id']}", headers=alice)
    assert pushed(fake, sid) == ({"GITHUB_TOKEN": "ghp_rotated", "NPM_TOKEN": "npm_123456"}, [])

    # GITHUB_TOKEN is in the container's own environment from boot, so removing it masks it there too
    client.delete(f"/sandboxes/{sid}/vault-secrets/{secret['id']}", headers=alice)
    assert pushed(fake, sid) == ({"NPM_TOKEN": "npm_123456"}, ["GITHUB_TOKEN"])

    client.put(f"/sandboxes/{sid}/secrets", json={"name": "OWN", "value": "own-value-1"}, headers=alice)
    assert pushed(fake, sid)[0] == {"NPM_TOKEN": "npm_123456", "OWN": "own-value-1"}

    client.delete(f"/vault/secrets/{other['id']}", headers=alice)
    assert pushed(fake, sid) == ({"OWN": "own-value-1"}, ["GITHUB_TOKEN"])
    # the sandbox kept running throughout
    assert runtime_of(sid) == runtime and fake.containers[runtime].running


def test_new_values_are_redacted_right_away(client, alice, make_sandbox, fake):
    secret = create(client, alice)
    sid = make_sandbox(secret_ids=[secret["id"]])["id"]
    client.patch(f"/vault/secrets/{secret['id']}", json={"value": "ghp_rotated_value"}, headers=alice)
    out = client.post(f"/sandboxes/{sid}/exec", json={"command": "echo ghp_rotated_value"}, headers=alice).json()
    assert out["stdout"] == "echo [redacted]"


def test_stopped_sandboxes_get_changes_on_their_next_boot(client, alice, make_sandbox, fake):
    secret = create(client, alice)
    sid = make_sandbox(secret_ids=[secret["id"]])["id"]
    client.post(f"/sandboxes/{sid}/stop", headers=alice)
    client.patch(f"/vault/secrets/{secret['id']}", json={"value": "ghp_while_stopped"}, headers=alice)
    client.post(f"/sandboxes/{sid}/start", headers=alice)
    assert secrets_env(fake.containers[runtime_of(sid)].env) == {"GITHUB_TOKEN": "ghp_while_stopped"}


def test_a_failed_push_does_not_fail_the_change(client, alice, make_sandbox, fake, monkeypatch):
    secret = create(client, alice)
    make_sandbox(secret_ids=[secret["id"]])

    def unreachable(*args):
        raise ConnectionError("host down")

    monkeypatch.setattr("server.docker.write_secrets", unreachable)
    res = client.patch(f"/vault/secrets/{secret['id']}", json={"value": "ghp_still_saved"}, headers=alice)
    assert res.status_code == 200


def test_expiry_and_rotation_reminders(client, alice, bob):
    now = datetime.now(UTC)
    soon = create(client, alice, name="EXPIRES_SOON", expires_at=(now + timedelta(days=3)).isoformat())
    assert soon["status"] == "expiring_soon" and soon["expires_at"].startswith(
        (now + timedelta(days=3)).strftime("%Y-%m-%d")
    )
    expired = create(client, alice, name="EXPIRED", expires_at=(now - timedelta(hours=1)).isoformat())
    assert expired["status"] == "expired"
    rotating = create(client, alice, name="ROTATE_MONTHLY", rotate_every_days=30)
    assert rotating["status"] == "ok" and rotating["rotation_due_at"] is not None
    fine = create(client, alice, name="FINE")
    assert fine["status"] == "ok" and fine["rotation_due_at"] is None

    # make the monthly one overdue: it was last rotated 40 days ago
    sql("UPDATE vault_secrets SET rotated_at = datetime('now', '-40 days') WHERE id = ?", rotating["id"])
    reminders = client.get("/vault/reminders", headers=alice).json()
    assert {r["name"]: r["status"] for r in reminders} == {
        "EXPIRES_SOON": "expiring_soon",
        "EXPIRED": "expired",
        "ROTATE_MONTHLY": "rotation_due",
    }
    assert reminders[0]["due_at"] <= reminders[-1]["due_at"]

    # rotating the value resets the clock
    client.patch(f"/vault/secrets/{rotating['id']}", json={"value": "new"}, headers=alice)
    assert "ROTATE_MONTHLY" not in {r["name"] for r in client.get("/vault/reminders", headers=alice).json()}

    # clearing the expiry clears its reminder; leaving fields out keeps them
    listed = client.patch(f"/vault/secrets/{expired['id']}", json={"expires_at": None}, headers=alice).json()
    assert next(s for s in listed if s["id"] == expired["id"])["status"] == "ok"
    listed = client.patch(f"/vault/secrets/{soon['id']}", json={"description": "x"}, headers=alice).json()
    assert next(s for s in listed if s["id"] == soon["id"])["status"] == "expiring_soon"
    assert client.get("/vault/reminders", headers=bob).json() == []


def test_reminders_are_logged_once_per_change(client, alice, caplog, monkeypatch):
    monkeypatch.setattr(vault_api, "_reminded", {})
    create(client, alice, name="OLD", expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat())
    vault_api.remind()
    vault_api.remind()
    logged = [r for r in caplog.records if "OLD has expired" in r.getMessage()]
    assert len(logged) == 1


def test_secret_used_as_the_agent_key(client, alice):
    client.put(
        "/agent/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5-5", "api_key": "sk-ant-1"},
        headers=alice,
    )
    [listed] = client.get("/vault/secrets", headers=alice).json()
    assert listed["name"] == "AGENT_ANTHROPIC_API_KEY" and listed["used_by_agent"] is True
