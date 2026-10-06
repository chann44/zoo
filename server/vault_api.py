import json
import uuid

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from db.connection import db_manager
from db.generated.models import User, VaultSecret
from db.generated.query import CreateVaultSecretParams, Querier
from server.auth_api import AuthApi, personal_workspace
from server.sandbox_api import SandboxApi
from server.security import audit, encrypt, secrets_changed

NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
ACTIVITY_LIMIT = 100


class VaultSecretRequest(BaseModel):
    name: str = Field(pattern=NAME_PATTERN)
    value: str = Field(min_length=1, max_length=8192)
    description: str | None = Field(default=None, max_length=200)


class VaultSecretUpdate(BaseModel):
    # None leaves the field as it is; the value can be replaced but never read back
    value: str | None = Field(default=None, min_length=1, max_length=8192)
    description: str | None = Field(default=None, max_length=200)


class SandboxRef(BaseModel):
    id: str
    name: str


class VaultSecretResponse(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: str
    updated_at: str
    last_used_at: str | None
    sandboxes: list[SandboxRef]


class AttachedSecretResponse(BaseModel):
    id: str
    name: str


class ActivityResponse(BaseModel):
    id: str
    action: str
    resource_type: str
    resource_id: str | None
    sandbox_id: str | None
    metadata: dict
    created_at: str


class VaultApi:
    def __init__(self, app: FastAPI, auth: AuthApi, sandboxes: SandboxApi):
        self.app = app
        self.auth = auth
        self.sandboxes = sandboxes
        self._register_routes()

    def secret(self, secret_id: str, user: User, db: Querier) -> VaultSecret:
        secret = db.get_vault_secret(id=secret_id)
        if secret is None or secret.user_id != user.id:
            raise HTTPException(status_code=404, detail="secret not found")
        return secret

    def _register_routes(self):
        current_user = self.auth.current_user

        @self.app.get("/vault/secrets", response_model=list[VaultSecretResponse])
        def list_secrets(
            user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[VaultSecretResponse]:
            return self._secrets(user, db)

        @self.app.post("/vault/secrets", response_model=list[VaultSecretResponse], status_code=201)
        def create_secret(
            payload: VaultSecretRequest,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ) -> list[VaultSecretResponse]:
            if db.get_vault_secret_by_name(user_id=user.id, name=payload.name) is not None:
                raise HTTPException(status_code=409, detail=f"{payload.name} already exists; update it instead")
            secret = db.create_vault_secret(
                CreateVaultSecretParams(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    name=payload.name,
                    description=(payload.description or "").strip() or None,
                    ciphertext=encrypt(payload.value, db, personal_workspace(user, db)),
                )
            )
            audit(db, user, "secret.create", "secret", secret.id, name=secret.name)
            return self._secrets(user, db)

        @self.app.patch("/vault/secrets/{secret_id}", response_model=list[VaultSecretResponse])
        def update_secret(
            secret_id: str,
            payload: VaultSecretUpdate,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ) -> list[VaultSecretResponse]:
            secrets_changed()
            secret = self.secret(secret_id, user, db)
            if payload.value is not None:
                db.update_vault_secret_value(
                    ciphertext=encrypt(payload.value, db, personal_workspace(user, db)), id=secret.id
                )
                audit(db, user, "secret.rotate", "secret", secret.id, name=secret.name)
            if payload.description is not None:
                db.update_vault_secret_description(description=payload.description.strip() or None, id=secret.id)
                audit(db, user, "secret.describe", "secret", secret.id, name=secret.name)
            return self._secrets(user, db)

        @self.app.delete("/vault/secrets/{secret_id}", response_model=list[VaultSecretResponse])
        def delete_secret(
            secret_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[VaultSecretResponse]:
            secrets_changed()
            secret = self.secret(secret_id, user, db)
            db.detach_vault_secret_everywhere(secret_id=secret.id)
            db.delete_vault_secret(id=secret.id)
            audit(db, user, "secret.delete", "secret", secret.id, name=secret.name)
            return self._secrets(user, db)

        @self.app.get("/sandboxes/{sandbox_id}/vault-secrets", response_model=list[AttachedSecretResponse])
        def attached_secrets(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[AttachedSecretResponse]:
            return self._attached(self.sandboxes.owned(sandbox_id, user, db).id, db)

        @self.app.put("/sandboxes/{sandbox_id}/vault-secrets/{secret_id}", response_model=list[AttachedSecretResponse])
        def attach_secret(
            sandbox_id: str,
            secret_id: str,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ) -> list[AttachedSecretResponse]:
            secrets_changed()
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            secret = self.secret(secret_id, user, db)
            db.attach_vault_secret(sandbox_id=sandbox.id, secret_id=secret.id)
            audit(db, user, "secret.attach", "secret", secret.id, sandbox.id, name=secret.name, sandbox=sandbox.name)
            return self._attached(sandbox.id, db)

        @self.app.delete(
            "/sandboxes/{sandbox_id}/vault-secrets/{secret_id}", response_model=list[AttachedSecretResponse]
        )
        def detach_secret(
            sandbox_id: str,
            secret_id: str,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ) -> list[AttachedSecretResponse]:
            secrets_changed()
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            secret = self.secret(secret_id, user, db)
            db.detach_vault_secret(sandbox_id=sandbox.id, secret_id=secret.id)
            audit(db, user, "secret.detach", "secret", secret.id, sandbox.id, name=secret.name, sandbox=sandbox.name)
            return self._attached(sandbox.id, db)

        @self.app.get("/vault/activity", response_model=list[ActivityResponse])
        def activity(
            user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[ActivityResponse]:
            return [
                ActivityResponse(
                    id=a.id,
                    action=a.action,
                    resource_type=a.resource_type,
                    resource_id=a.resource_id,
                    sandbox_id=a.sandbox_id,
                    metadata=json.loads(a.metadata or "{}"),
                    created_at=a.created_at,
                )
                for a in db.list_vault_audit_logs(workspace_id=personal_workspace(user, db), limit=ACTIVITY_LIMIT)
            ]

    def _secrets(self, user: User, db: Querier) -> list[VaultSecretResponse]:
        grants: dict[str, list[SandboxRef]] = {}
        for g in db.list_vault_grants_by_user(created_by=user.id):
            grants.setdefault(g.secret_id, []).append(SandboxRef(id=g.sandbox_id, name=g.sandbox_name))
        return [
            VaultSecretResponse(
                id=s.id,
                name=s.name,
                description=s.description,
                created_at=s.created_at,
                updated_at=s.updated_at,
                last_used_at=s.last_used_at,
                sandboxes=grants.get(s.id, []),
            )
            for s in db.list_vault_secrets_by_user(user_id=user.id)
        ]

    def _attached(self, sandbox_id: str, db: Querier) -> list[AttachedSecretResponse]:
        return [
            AttachedSecretResponse(id=r.id, name=r.name) for r in db.list_sandbox_vault_secrets(sandbox_id=sandbox_id)
        ]
