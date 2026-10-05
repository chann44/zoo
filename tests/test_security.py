import pytest
from cryptography.fernet import InvalidToken

from db.connection import db_manager
from server import security
from server.sandbox_api import PROFILE_DIR
from server.security import REDACTED, decrypt, encrypt, redact


def test_redact_masks_secrets_anywhere_in_a_result():
    result = {"stdout": "token=abcdef123", "lines": ["abcdef123", ("x", "abcdef123")], "code": 0, "none": None}
    assert redact(result, ["abcdef123"]) == {
        "stdout": f"token={REDACTED}",
        "lines": [REDACTED, ("x", REDACTED)],
        "code": 0,
        "none": None,
    }


def test_redact_prefers_longest_match_and_skips_short_values():
    assert redact("abcdef-long-secret", ["abcdef", "abcdef-long-secret"]) == REDACTED
    assert redact("id=1 abc", ["abc", "1"]) == "id=1 abc"
    assert redact("nothing", []) == "nothing"


def test_encrypt_round_trip_and_tamper_detection():
    token = encrypt("hunter2-secret")
    assert token != "hunter2-secret"
    assert decrypt(token) == "hunter2-secret"
    with pytest.raises(InvalidToken):
        decrypt(token[:-4] + "AAAA")


def test_secrets_key_rotation(client, alice, sandbox, monkeypatch):
    monkeypatch.setenv("ZOO_SECRETS_KEY", "old-key")
    client.post("/vault/secrets", json={"name": "VAULT", "value": "vault-value"}, headers=alice)
    client.put(f"/sandboxes/{sandbox['id']}/secrets", json={"name": "LOCAL", "value": "local-value"}, headers=alice)

    monkeypatch.setenv("ZOO_SECRETS_KEY", "new-key")
    with db_manager.session() as db, pytest.raises(InvalidToken):
        decrypt(next(iter(db.list_all_vault_secrets())).ciphertext)

    monkeypatch.setenv("ZOO_SECRETS_KEY_PREVIOUS", "old-key")
    with db_manager.session() as db:
        counts = security.rotate(db, PROFILE_DIR)
    assert counts["vault_secrets"] == 1 and counts["sandbox_secrets"] == 1

    monkeypatch.delenv("ZOO_SECRETS_KEY_PREVIOUS")
    with db_manager.session() as db:
        assert decrypt(next(iter(db.list_all_vault_secrets())).ciphertext) == "vault-value"
        assert decrypt(next(iter(db.list_all_sandbox_secrets())).secret_ref) == "local-value"


def test_jwt_secret_still_decrypts_when_secrets_key_is_added(monkeypatch):
    token = encrypt("legacy")
    monkeypatch.setenv("ZOO_SECRETS_KEY", "brand-new-key")
    assert decrypt(token) == "legacy"
