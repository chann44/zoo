import base64
import hashlib
import os

from cryptography.fernet import Fernet

from db.generated.models import Sandbox
from db.generated.query import Querier
from server.docker import apply_apps, apply_network

APP_ACTION = "launch"


def _fernet() -> Fernet:
    key = hashlib.sha256(os.environ["JWT_SECRET"].encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def secret_env(sandbox: Sandbox, db: Querier) -> dict[str, str]:
    env = {}
    for row in db.list_sandbox_secrets(sandbox_id=sandbox.id):
        if row.enabled:
            env[row.name] = decrypt(db.get_sandbox_secret(id=row.id).secret_ref)
    return env


def enforce(sandbox: Sandbox, db: Querier):
    if sandbox.status != "running" or not sandbox.runtime_id:
        return
    policy = db.get_sandbox_network_policy(sandbox_id=sandbox.id)
    if policy is not None:
        rules = [(r.rule_type, r.value, r.effect) for r in db.list_sandbox_network_rules(policy_id=policy.id)]
        apply_network(sandbox.runtime_id, policy.default_action, bool(policy.allow_dns), rules)
    apply_apps(
        sandbox.runtime_id,
        {p.app_slug: p.effect for p in db.list_sandbox_app_permissions(sandbox_id=sandbox.id) if p.action == APP_ACTION},
    )
