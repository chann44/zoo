import base64
import hashlib
import json
import os
import secrets
import uuid
from typing import Any

from cryptography.fernet import Fernet, MultiFernet

from db.generated.models import Sandbox, User
from db.generated.query import CreateAuditLogParams, Querier
from server.auth_api import personal_workspace
from server.runtime import apply_apps, apply_network

APP_ACTION = "launch"
REDACTED = "[redacted]"
# shorter values would turn ordinary output into a wall of [redacted]
MIN_REDACT_LENGTH = 6
VNC_PASSWORD = "vnc_password"


def _key(material: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest()))


def require_secrets_key(db: Querier):
    """New installs must set ZOO_SECRETS_KEY. Installs that already have users may keep the JWT_SECRET-derived key
    until they set one and run `make rotate-secrets`."""
    if os.environ.get("ZOO_SECRETS_KEY") or next(iter(db.list_users()), None) is not None:
        return
    raise RuntimeError(
        "ZOO_SECRETS_KEY is not set. Set it to a long random string, separate from JWT_SECRET "
        "(e.g. `openssl rand -base64 48`); it encrypts stored secrets, so keep it safe and stable"
    )


def _fernet() -> MultiFernet:
    # ZOO_SECRETS_KEY encrypts; older keys (and the JWT_SECRET fallback) only decrypt until rotate() rewraps
    keys = [os.environ.get("ZOO_SECRETS_KEY") or os.environ["JWT_SECRET"]]
    keys += [k for k in os.environ.get("ZOO_SECRETS_KEY_PREVIOUS", "").split(",") if k]
    keys.append(os.environ["JWT_SECRET"])
    return MultiFernet([_key(k) for k in dict.fromkeys(keys)])


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    return _fernet().decrypt(token)


def write_private(path: str, data: bytes):
    tmp = f"{path}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def secret_values(sandbox: Sandbox, db: Querier) -> dict[str, str]:
    # vault secrets first so a sandbox's own secret of the same name wins
    env = {row.name: decrypt(row.ciphertext) for row in db.list_sandbox_vault_secrets(sandbox_id=sandbox.id)}
    for row in db.list_sandbox_secrets(sandbox_id=sandbox.id):
        if row.enabled:
            env[row.name] = decrypt(db.get_sandbox_secret(id=row.id).secret_ref)
    return env


# secret values per sandbox, kept so tool output is redacted without decrypting every secret on every call:
# what it booted with (still in its env after a later change) and what is attached now (cleared on any change)
_booted: dict[str, list[str]] = {}
_attached: dict[str, list[str]] = {}


def remember_secrets(sandbox_id: str, values: list[str]):
    _booted[sandbox_id] = values
    _attached.pop(sandbox_id, None)


def forget_secrets(sandbox_id: str):
    _booted.pop(sandbox_id, None)
    _attached.pop(sandbox_id, None)


def secrets_changed(sandbox_id: str | None = None):
    """Drops cached attached values for one sandbox, or for all after a vault secret (shared by many) changes."""
    if sandbox_id is None:
        _attached.clear()
    else:
        _attached.pop(sandbox_id, None)


def redaction_values(sandbox: Sandbox, db: Querier) -> list[str]:
    """The secret values to mask in a sandbox's tool output."""
    attached = _attached.get(sandbox.id)
    if attached is None:
        attached = _attached[sandbox.id] = [*secret_values(sandbox, db).values(), vnc_password(sandbox)]
    return [*_booted.get(sandbox.id, []), *attached]


def vnc_password(sandbox: Sandbox) -> str:
    """The password of the sandbox's x11vnc, or "" for a sandbox booted before it had one (its x11vnc has none)."""
    stored = json.loads(sandbox.config or "{}").get(VNC_PASSWORD)
    return decrypt(stored) if stored else ""


def ensure_vnc_password(sandbox: Sandbox, db: Querier) -> str:
    """Makes the sandbox's x11vnc password on its first boot and keeps it, encrypted, in its config. Only the API
    knows it: the viewer proxy logs in with it and offers the browser no-auth."""
    config = json.loads(sandbox.config or "{}")
    if VNC_PASSWORD not in config:
        # VNC authentication only uses the first 8 characters
        config[VNC_PASSWORD] = encrypt(secrets.token_urlsafe(6))
        db.update_sandbox(name=sandbox.name, resources=sandbox.resources, config=json.dumps(config), id=sandbox.id)
    return decrypt(config[VNC_PASSWORD])


def secret_env(sandbox: Sandbox, db: Querier) -> dict[str, str]:
    for row in db.list_sandbox_vault_secrets(sandbox_id=sandbox.id):
        db.mark_vault_secret_used(id=row.id)
    return secret_values(sandbox, db)


def redact(value: Any, secrets: list[str]) -> Any:
    """Masks secret values anywhere in a tool result so they never reach logs or agents."""
    secrets = sorted((s for s in secrets if len(s) >= MIN_REDACT_LENGTH), key=len, reverse=True)
    if not secrets:
        return value

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            for s in secrets:
                v = v.replace(s, REDACTED)
            return v
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return type(v)(walk(x) for x in v)
        return v

    return walk(value)


def rotate(db: Querier, profile_dir: str) -> dict[str, int]:
    """Re-encrypts every stored secret and profile with the current ZOO_SECRETS_KEY."""
    f = _fernet()
    counts = {"vault_secrets": 0, "sandbox_secrets": 0, "agent_keys": 0, "vnc_passwords": 0, "profiles": 0}
    for row in list(db.list_all_vault_secrets()):
        db.rewrap_vault_secret(ciphertext=f.rotate(row.ciphertext.encode()).decode(), id=row.id)
        counts["vault_secrets"] += 1
    for row in list(db.list_all_sandbox_secrets()):
        db.rewrap_sandbox_secret(secret_ref=f.rotate(row.secret_ref.encode()).decode(), id=row.id)
        counts["sandbox_secrets"] += 1
    for row in list(db.list_all_agent_setting_keys()):
        db.rewrap_agent_setting_key(api_key_ref=f.rotate(row.api_key_ref.encode()).decode(), user_id=row.user_id)
        counts["agent_keys"] += 1
    for sandbox in list(db.list_all_sandboxes()):
        config = json.loads(sandbox.config or "{}")
        if config.get(VNC_PASSWORD):
            config[VNC_PASSWORD] = f.rotate(config[VNC_PASSWORD].encode()).decode()
            db.update_sandbox(name=sandbox.name, resources=sandbox.resources, config=json.dumps(config), id=sandbox.id)
            counts["vnc_passwords"] += 1
    for profile in list(db.list_all_profiles()):
        path = os.path.join(profile_dir, f"{profile.id}.tar")
        if not os.path.exists(path):
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        token = f.rotate(data) if profile.encrypted else f.encrypt(data)
        write_private(path, token)
        db.set_profile_encrypted(encrypted=1, size_bytes=profile.size_bytes, id=profile.id)
        counts["profiles"] += 1
    return counts


def enforce(sandbox: Sandbox, db: Querier):
    if sandbox.status != "running" or not sandbox.runtime_id:
        return
    policy = db.get_sandbox_network_policy(sandbox_id=sandbox.id)
    if policy is not None:
        rules = [(r.rule_type, r.value, r.effect) for r in db.list_sandbox_network_rules(policy_id=policy.id)]
        apply_network(sandbox.runtime_id, policy.default_action, bool(policy.allow_dns), rules)
    apply_apps(
        sandbox.runtime_id,
        {
            p.app_slug: p.effect
            for p in db.list_sandbox_app_permissions(sandbox_id=sandbox.id)
            if p.action == APP_ACTION
        },
    )


def audit(
    db: Querier,
    user: User,
    action: str,
    resource_type: str,
    resource_id: str | None,
    sandbox_id: str | None = None,
    **metadata,
):
    """Records who touched which secret or profile. Never pass a secret value in metadata."""
    db.create_audit_log(
        CreateAuditLogParams(
            id=str(uuid.uuid4()),
            workspace_id=personal_workspace(user, db),
            actor_id=user.id,
            sandbox_id=sandbox_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=json.dumps(metadata),
        )
    )
