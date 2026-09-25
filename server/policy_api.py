import uuid
from typing import Literal

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field

from logger.logger import logger
from server.auth_api import AuthApi
from server.sandbox_api import SandboxApi
from server.tools import AppTools
from db.generated.query import (
    Querier,
    CreateAppParams,
    CreateSandboxNetworkRuleParams,
    GrantSandboxAppPermissionParams,
    UpsertSandboxPermissionParams,
)
from db.generated.models import Sandbox, SandboxNetworkPolicy, User
from db.connection import db_manager

Effect = Literal["allow", "deny"]

AGENT_PERMISSIONS = {
    ("shell", "exec"): "Run shell commands",
    ("screen", "read"): "Take screenshots",
    ("input", "control"): "Control mouse and keyboard",
}

APP_ACTION = "launch"


class PermissionResponse(BaseModel):
    permission: str
    action: str
    label: str
    effect: Effect


class PermissionRequest(BaseModel):
    permission: str
    action: str
    effect: Effect


class NetworkRuleResponse(BaseModel):
    id: str
    rule_type: str
    value: str
    effect: Effect


class NetworkResponse(BaseModel):
    default_action: Effect
    allow_dns: bool
    rules: list[NetworkRuleResponse]


class NetworkPolicyRequest(BaseModel):
    default_action: Effect
    allow_dns: bool


class NetworkRuleRequest(BaseModel):
    rule_type: Literal["domain", "ip", "cidr"]
    value: str = Field(min_length=1, max_length=253)
    effect: Effect


class AppResponse(BaseModel):
    name: str
    binary: str
    effect: Effect


class AppPermissionRequest(BaseModel):
    effect: Effect


class SandboxPolicyApi:
    def __init__(self, app: FastAPI, auth: AuthApi, sandboxes: SandboxApi):
        self.logger = logger
        self.app = app
        self.auth = auth
        self.sandboxes = sandboxes
        self._register_routes()

    def _register_routes(self):
        current_user = self.auth.current_user

        @self.app.get("/sandboxes/{sandbox_id}/permissions", response_model=list[PermissionResponse])
        def list_permissions(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[PermissionResponse]:
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            return self._permissions(sandbox, db)

        @self.app.put("/sandboxes/{sandbox_id}/permissions", response_model=list[PermissionResponse])
        def set_permission(
            sandbox_id: str,
            payload: PermissionRequest,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ) -> list[PermissionResponse]:
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            if (payload.permission, payload.action) not in AGENT_PERMISSIONS:
                raise HTTPException(status_code=422, detail="unknown permission")
            db.upsert_sandbox_permission(
                UpsertSandboxPermissionParams(
                    id=str(uuid.uuid4()),
                    sandbox_id=sandbox.id,
                    permission=payload.permission,
                    action=payload.action,
                    effect=payload.effect,
                    rules="{}",
                )
            )
            return self._permissions(sandbox, db)

        @self.app.get("/sandboxes/{sandbox_id}/network", response_model=NetworkResponse)
        def get_network(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> NetworkResponse:
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            return self._network(sandbox, db)

        @self.app.put("/sandboxes/{sandbox_id}/network", response_model=NetworkResponse)
        def set_network(
            sandbox_id: str,
            payload: NetworkPolicyRequest,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ) -> NetworkResponse:
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            db.upsert_sandbox_network_policy(
                id=str(uuid.uuid4()),
                sandbox_id=sandbox.id,
                default_action=payload.default_action,
                allow_dns=int(payload.allow_dns),
            )
            return self._network(sandbox, db)

        @self.app.post("/sandboxes/{sandbox_id}/network/rules", response_model=NetworkResponse, status_code=201)
        def add_rule(
            sandbox_id: str,
            payload: NetworkRuleRequest,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ) -> NetworkResponse:
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            policy = self._policy(sandbox, db)
            db.create_sandbox_network_rule(
                CreateSandboxNetworkRuleParams(
                    id=str(uuid.uuid4()),
                    policy_id=policy.id,
                    rule_type=payload.rule_type,
                    value=payload.value.strip().lower(),
                    effect=payload.effect,
                )
            )
            return self._network(sandbox, db)

        @self.app.delete("/sandboxes/{sandbox_id}/network/rules/{rule_id}", response_model=NetworkResponse)
        def delete_rule(
            sandbox_id: str,
            rule_id: str,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ) -> NetworkResponse:
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            policy = db.get_sandbox_network_policy(sandbox_id=sandbox.id)
            rule = db.get_sandbox_network_rule(id=rule_id)
            if policy is None or rule is None or rule.policy_id != policy.id:
                raise HTTPException(status_code=404, detail="rule not found")
            db.delete_sandbox_network_rule(id=rule.id)
            return self._network(sandbox, db)

        @self.app.get("/sandboxes/{sandbox_id}/apps", response_model=list[AppResponse])
        def list_apps(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[AppResponse]:
            sandbox = self.sandboxes.running(sandbox_id, user, db)
            return self._apps(sandbox, db)

        @self.app.put("/sandboxes/{sandbox_id}/apps/{binary}", response_model=list[AppResponse])
        def set_app(
            sandbox_id: str,
            binary: str,
            payload: AppPermissionRequest,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ) -> list[AppResponse]:
            sandbox = self.sandboxes.running(sandbox_id, user, db)
            installed = {a["binary"]: a for a in AppTools.installed_apps(sandbox.runtime_id)["gui_apps"]}
            if binary not in installed:
                raise HTTPException(status_code=404, detail="app not installed in this sandbox")

            app = next((a for a in db.list_apps_by_workspace(workspace_id=sandbox.workspace_id) if a.slug == binary), None)
            if app is None:
                app = db.create_app(
                    CreateAppParams(
                        id=str(uuid.uuid4()),
                        workspace_id=sandbox.workspace_id,
                        name=installed[binary]["name"],
                        slug=binary,
                        description=None,
                        install_config="{}",
                    )
                )
            db.grant_sandbox_app_permission(
                GrantSandboxAppPermissionParams(
                    id=str(uuid.uuid4()),
                    sandbox_id=sandbox.id,
                    app_id=app.id,
                    action=APP_ACTION,
                    effect=payload.effect,
                )
            )
            return self._apps(sandbox, db)

    def _permissions(self, sandbox: Sandbox, db: Querier) -> list[PermissionResponse]:
        stored = {(p.permission, p.action): p.effect for p in db.list_sandbox_permissions(sandbox_id=sandbox.id)}
        return [
            PermissionResponse(permission=p, action=a, label=label, effect=stored.get((p, a), "allow"))
            for (p, a), label in AGENT_PERMISSIONS.items()
        ]

    def _policy(self, sandbox: Sandbox, db: Querier) -> SandboxNetworkPolicy:
        policy = db.get_sandbox_network_policy(sandbox_id=sandbox.id)
        if policy is None:
            policy = db.upsert_sandbox_network_policy(
                id=str(uuid.uuid4()), sandbox_id=sandbox.id, default_action="allow", allow_dns=1
            )
        return policy

    def _network(self, sandbox: Sandbox, db: Querier) -> NetworkResponse:
        policy = db.get_sandbox_network_policy(sandbox_id=sandbox.id)
        if policy is None:
            return NetworkResponse(default_action="allow", allow_dns=True, rules=[])
        rules = [
            NetworkRuleResponse(id=r.id, rule_type=r.rule_type, value=r.value, effect=r.effect)
            for r in db.list_sandbox_network_rules(policy_id=policy.id)
        ]
        return NetworkResponse(default_action=policy.default_action, allow_dns=bool(policy.allow_dns), rules=rules)

    def _apps(self, sandbox: Sandbox, db: Querier) -> list[AppResponse]:
        stored = {
            p.app_slug: p.effect
            for p in db.list_sandbox_app_permissions(sandbox_id=sandbox.id)
            if p.action == APP_ACTION
        }
        apps = AppTools.installed_apps(sandbox.runtime_id)["gui_apps"]
        seen = {}
        for a in apps:
            if a["binary"] and a["binary"] not in seen:
                seen[a["binary"]] = AppResponse(name=a["name"], binary=a["binary"], effect=stored.get(a["binary"], "allow"))
        return sorted(seen.values(), key=lambda a: a.name.lower())

