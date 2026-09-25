import asyncio
import base64
import inspect
import json
import os
import uuid

import websockets
from typing import Any, Literal

from fastapi import FastAPI, Depends, HTTPException, Request, Response, WebSocket, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from logger.logger import logger
from server.auth_api import AuthApi, personal_workspace
from server.docker import (
    CODE_IMAGE,
    IMAGE,
    connect,
    copy_volume,
    import_dir,
    export_home,
    import_home,
    is_running,
    remove_container,
    remove_volume,
    run_container,
    wait_for_vnc,
)
from server.proxy import forward_client_to_target, forward_target_to_client
from server.registry import KINDS, TOOLS, open_url
from server.schema import ExecRequest, ExecResponse
from server.security import enforce, secret_env
from server.telemetry import tracer
from db.generated.query import (
    Querier,
    CreateAgentSessionParams,
    CreateSandboxParams,
    CreateSandboxImageParams,
    CreateSandboxImageVersionParams,
)
from db.generated.models import Sandbox, SandboxImageVersion, User
from db.connection import db_manager

IMAGE_SLUG = "zoo-sandbox"
IMAGE_VERSION = "latest"
AUTO = "auto"
PROFILE_DIR = os.environ.get("PROFILE_DIR", "data/profiles")
PROFILE_APPS = {"firefox": ".mozilla", "chromium": ".config/chromium", "chrome": ".config/google-chrome", "vscode": ".config/Code"}
BROWSER_HOME = os.environ.get("ZOO_BROWSER_HOME", "https://duckduckgo.com")


class CreateSandboxRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    kind: Literal["desktop", "browser", "code"] = "desktop"
    server_id: str | None = None
    profile_ids: list[str] = []


class MoveSandboxRequest(BaseModel):
    server_id: str | None = None


class SandboxResponse(BaseModel):
    id: str
    name: str
    kind: str
    server_id: str | None
    status: str
    error_message: str | None
    started_at: str | None
    created_at: str


class ToolExecutionResponse(BaseModel):
    id: str
    tool_name: str
    status: str
    input: str
    error_message: str | None
    created_at: str
    completed_at: str | None


class DeleteSandboxResponse(BaseModel):
    deleted: bool = True
    id: str


def to_response(sandbox: Sandbox) -> SandboxResponse:
    return SandboxResponse(
        id=sandbox.id,
        name=sandbox.name,
        kind=sandbox.kind,
        server_id=sandbox.server_id,
        status=sandbox.status,
        error_message=sandbox.error_message,
        started_at=sandbox.started_at,
        created_at=sandbox.created_at,
    )


class SandboxApi:
    def __init__(self, app: FastAPI, auth: AuthApi):
        self.logger = logger
        self.app = app
        self.auth = auth
        self._register_routes()

    def _register_routes(self):
        current_user = self.auth.current_user

        @self.app.get("/sandboxes", response_model=list[SandboxResponse])
        def list_sandboxes(
            user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[SandboxResponse]:
            return [to_response(s) for s in db.list_sandboxes_by_user(created_by=user.id)]

        @self.app.post("/sandboxes", response_model=SandboxResponse, status_code=201)
        def create_sandbox(
            payload: CreateSandboxRequest,
            background: BackgroundTasks,
            user: User = Depends(current_user),
        ) -> SandboxResponse:
            with db_manager.session() as db:
                sandbox = self.create(payload, user, db)
            background.add_task(self.boot, sandbox.id)
            return to_response(sandbox)

        @self.app.get("/sandboxes/{sandbox_id}", response_model=SandboxResponse)
        def get_sandbox(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> SandboxResponse:
            return to_response(self.owned(sandbox_id, user, db))

        @self.app.post("/sandboxes/{sandbox_id}/start", response_model=SandboxResponse)
        def start_sandbox(
            sandbox_id: str, background: BackgroundTasks, user: User = Depends(current_user)
        ) -> SandboxResponse:
            with db_manager.session() as db:
                sandbox = self.owned(sandbox_id, user, db)
                if sandbox.status in ("running", "provisioning"):
                    raise HTTPException(status_code=409, detail=f"sandbox is {sandbox.status}")
                sandbox = db.update_sandbox_status(status="provisioning", id=sandbox.id)
            background.add_task(self.boot, sandbox.id)
            return to_response(sandbox)

        @self.app.post("/sandboxes/{sandbox_id}/stop", response_model=SandboxResponse)
        def stop_sandbox(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> SandboxResponse:
            sandbox = self.owned(sandbox_id, user, db)
            return to_response(self.halt(sandbox, db))

        @self.app.delete("/sandboxes/{sandbox_id}", response_model=DeleteSandboxResponse)
        def delete_sandbox(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> DeleteSandboxResponse:
            sandbox = self.owned(sandbox_id, user, db)
            if sandbox.runtime_id:
                remove_container(sandbox.runtime_id)
            remove_volume(sandbox.id, self.server_of(sandbox, db))
            db.soft_delete_sandbox(id=sandbox.id)
            self.logger.info("sandbox deleted", extra={"sandbox_id": sandbox.id})
            return DeleteSandboxResponse(id=sandbox.id)

        @self.app.post("/sandboxes/{sandbox_id}/move", response_model=SandboxResponse)
        async def move_sandbox(
            sandbox_id: str, payload: MoveSandboxRequest, user: User = Depends(current_user)
        ) -> SandboxResponse:
            with db_manager.session() as db:
                sandbox = self.owned(sandbox_id, user, db)
                if sandbox.status in ("running", "provisioning"):
                    raise HTTPException(status_code=409, detail="stop the sandbox before moving it")
                target = self.place(payload.server_id, user, db)
                if target == sandbox.server_id:
                    return to_response(sandbox)
                source = self.server_of(sandbox, db)
                dest = db.get_server(id=target) if target else None
            try:
                await asyncio.to_thread(copy_volume, sandbox.id, source, dest)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"move failed: {e}")
            with db_manager.session() as db:
                return to_response(db.set_sandbox_placement(server_id=target, kind=sandbox.kind, id=sandbox.id))

        @self.app.get("/tools")
        def list_tools(kind: str | None = None, user: User = Depends(current_user)) -> list[dict]:
            allowed = KINDS.get(kind or "desktop")
            return [t.schema() for t in TOOLS.values() if allowed is None or t.category in allowed]

        @self.app.post("/sandboxes/{sandbox_id}/tools/{name}")
        async def call_tool(
            sandbox_id: str, name: str, args: dict[str, Any] | None = None, user: User = Depends(current_user)
        ) -> Any:
            return await self.run_tool(user, sandbox_id, name, args or {}, "api")

        @self.app.post("/sandboxes/{sandbox_id}/screenshot")
        async def screenshot(sandbox_id: str, user: User = Depends(current_user)):
            data = await self.run_tool(user, sandbox_id, "screenshot", {}, "api")
            return Response(content=base64.b64decode(data), media_type="image/png")

        @self.app.post("/sandboxes/{sandbox_id}/exec", response_model=ExecResponse)
        async def execute(sandbox_id: str, exec_req: ExecRequest, user: User = Depends(current_user)) -> ExecResponse:
            result = await self.run_tool(user, sandbox_id, "execute_command", exec_req.model_dump(), "api")
            return ExecResponse(sandbox_id=sandbox_id, **result)

        @self.app.get("/sandboxes/{sandbox_id}/executions", response_model=list[ToolExecutionResponse])
        def list_executions(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[ToolExecutionResponse]:
            sandbox = self.owned(sandbox_id, user, db)
            return [
                ToolExecutionResponse(**{k: getattr(e, k) for k in ToolExecutionResponse.model_fields})
                for e in db.list_tool_executions_by_sandbox(sandbox_id=sandbox.id, limit=100)
            ]

        @self.app.get("/sandboxes/{sandbox_id}/backup")
        def backup(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ):
            sandbox = self.running(sandbox_id, user, db)
            return StreamingResponse(
                export_home(sandbox.runtime_id),
                media_type="application/x-tar",
                headers={"Content-Disposition": f'attachment; filename="{sandbox.name}.tar"'},
            )

        @self.app.post("/sandboxes/{sandbox_id}/restore", response_model=SandboxResponse)
        async def restore(
            sandbox_id: str, request: Request, user: User = Depends(current_user)
        ) -> SandboxResponse:
            with db_manager.session() as db:
                sandbox = self.running(sandbox_id, user, db)
            await asyncio.to_thread(import_home, sandbox.runtime_id, await request.body())
            return to_response(sandbox)

        self.app.websocket("/sandboxes/{sandbox_id}/ws")(self.proxy)

    def owned(self, sandbox_id: str, user: User, db: Querier) -> Sandbox:
        sandbox = db.get_sandbox(id=sandbox_id)
        if sandbox is None or sandbox.created_by != user.id or sandbox.status == "deleted":
            raise HTTPException(status_code=404, detail="sandbox not found")
        return sandbox

    def allowed(self, sandbox_id: str, user: User, db: Querier, permission: str, action: str) -> Sandbox:
        sandbox = self.running(sandbox_id, user, db)
        stored = db.get_sandbox_permission(sandbox_id=sandbox.id, permission=permission, action=action)
        if stored is not None and stored.effect != "allow":
            raise HTTPException(status_code=403, detail=f"{permission}.{action} is denied for this sandbox")
        return sandbox

    def running(self, sandbox_id: str, user: User, db: Querier) -> Sandbox:
        sandbox = self.owned(sandbox_id, user, db)
        if sandbox.status != "running" or not sandbox.runtime_id:
            raise HTTPException(status_code=409, detail=f"sandbox is {sandbox.status}")
        return sandbox

    def server_of(self, sandbox: Sandbox, db: Querier):
        return db.get_server(id=sandbox.server_id) if sandbox.server_id else None

    def place(self, server_id: str | None, user: User, db: Querier) -> str | None:
        servers = db.list_servers_by_user(created_by=user.id)
        if server_id == AUTO:
            load = {s.id: 0 for s in servers}
            local = 0
            for sb in db.list_all_sandboxes():
                if sb.status == "running":
                    if sb.server_id in load:
                        load[sb.server_id] += 1
                    elif sb.server_id is None:
                        local += 1
            best = min(load, key=load.get, default=None)
            return best if best is not None and load[best] < local else None
        if server_id is not None and server_id not in {s.id for s in servers}:
            raise HTTPException(status_code=404, detail="server not found")
        return server_id

    def _default_image_version(self, user: User, db: Querier) -> tuple[str, SandboxImageVersion]:
        workspace_id = personal_workspace(user, db)
        image = next((i for i in db.list_sandbox_images(workspace_id=workspace_id) if i.slug == IMAGE_SLUG), None)
        if image is None:
            image = db.create_sandbox_image(
                CreateSandboxImageParams(
                    id=str(uuid.uuid4()),
                    workspace_id=workspace_id,
                    name="Zoo desktop",
                    slug=IMAGE_SLUG,
                    description=None,
                    is_public=0,
                    created_by=user.id,
                )
            )

        version = db.get_sandbox_image_version_by_tag(image_id=image.id, version=IMAGE_VERSION)
        if version is None:
            version = db.create_sandbox_image_version(
                CreateSandboxImageVersionParams(
                    id=str(uuid.uuid4()),
                    image_id=image.id,
                    version=IMAGE_VERSION,
                    image_uri=IMAGE,
                    image_digest=None,
                    build_config="{}",
                    default_resources="{}",
                    created_by=user.id,
                )
            )
        return workspace_id, version

    def create(self, payload: CreateSandboxRequest, user: User, db: Querier) -> Sandbox:
        workspace_id, version = self._default_image_version(user, db)
        server_id = self.place(payload.server_id, user, db)
        for profile_id in payload.profile_ids:
            profile = db.get_profile(id=profile_id)
            if profile is None or profile.user_id != user.id:
                raise HTTPException(status_code=404, detail="profile not found")
        sandbox_id = str(uuid.uuid4())
        sandbox = db.create_sandbox(
            CreateSandboxParams(
                id=sandbox_id,
                workspace_id=workspace_id,
                image_version_id=version.id,
                created_by=user.id,
                name=payload.name or f"sandbox-{sandbox_id[:8]}",
                runtime="docker",
                resources="{}",
                config=json.dumps({"profiles": payload.profile_ids}),
            )
        )
        if sandbox is None:
            raise HTTPException(status_code=500, detail="failed to create sandbox")
        db.set_sandbox_placement(server_id=server_id, kind=payload.kind, id=sandbox.id)
        sandbox = db.update_sandbox_status(status="provisioning", id=sandbox.id)
        self.logger.info("sandbox created", extra={"sandbox_id": sandbox.id, "user_id": user.id})
        return sandbox

    def halt(self, sandbox: Sandbox, db: Querier) -> Sandbox:
        if sandbox.runtime_id:
            remove_container(sandbox.runtime_id)
        db.clear_sandbox_runtime(id=sandbox.id)
        return db.set_sandbox_stopped(id=sandbox.id)

    def boot(self, sandbox_id: str):
        with db_manager.session() as db:
            sandbox = db.get_sandbox(id=sandbox_id)
            image_uri = db.get_sandbox_image_version(id=sandbox.image_version_id).image_uri
            env = secret_env(sandbox, db)
            server = self.server_of(sandbox, db)
            desktop = sandbox.kind != "code"
            profiles = [db.get_profile(id=p) for p in json.loads(sandbox.config or "{}").get("profiles", [])]
            if sandbox.runtime_id:
                remove_container(sandbox.runtime_id)
        try:
            container_id, host, port = run_container(
                f"zoo-sandbox-{sandbox_id}", image_uri if desktop else CODE_IMAGE, sandbox_id, env, server, desktop
            )
        except Exception as e:
            self.logger.error("sandbox provisioning failed", extra={"sandbox_id": sandbox_id, "error": str(e)})
            with db_manager.session() as db:
                db.set_sandbox_failed(error_message=str(e), id=sandbox_id)
            return

        with db_manager.session() as db:
            sandbox = db.get_sandbox(id=sandbox_id)
            if sandbox is None or sandbox.status == "deleted":
                remove_container(container_id)
                return
            db.update_sandbox_runtime(
                runtime_id=container_id,
                runtime_host=host,
                access_url=f"ws://{host}:{port}/websockify" if desktop else None,
                id=sandbox_id,
            )

        for profile in profiles:
            if profile is not None:
                self.apply_profile(container_id, profile)
        ready = wait_for_vnc(host, port) if desktop else True
        with db_manager.session() as db:
            if not ready:
                db.set_sandbox_failed(error_message="desktop did not come up in time", id=sandbox_id)
                return
            if db.get_sandbox(id=sandbox_id).status == "deleted":
                return
            sandbox = db.set_sandbox_started(id=sandbox_id)
            try:
                enforce(sandbox, db)
            except Exception as e:
                self.logger.error("policy enforcement failed", extra={"sandbox_id": sandbox_id, "error": str(e)})
        if sandbox.kind == "browser":
            try:
                open_url(container_id, BROWSER_HOME)
            except Exception as e:
                self.logger.error("browser launch failed", extra={"sandbox_id": sandbox_id, "error": str(e)})
        self.logger.info("sandbox running", extra={"sandbox_id": sandbox_id, "host": host, "port": port})

    def apply_profile(self, container_id: str, profile):
        path = PROFILE_APPS[profile.app]
        parent = os.path.dirname(f"/home/zoo/{path}")
        with open(os.path.join(PROFILE_DIR, f"{profile.id}.tar"), "rb") as f:
            data = f.read()
        import_dir(container_id, parent, data)

    def alive(self, sandbox: Sandbox) -> bool:
        if not sandbox.runtime_id:
            return False
        try:
            return is_running(sandbox.runtime_id)
        except Exception:
            return True

    def reconcile(self, startup: bool = False):
        with db_manager.session() as db:
            if startup:
                for server in db.list_all_servers():
                    try:
                        connect(server.id, server.docker_url)
                    except Exception as e:
                        self.logger.error("server unreachable", extra={"server_id": server.id, "error": str(e)})
            for sandbox in db.list_all_sandboxes():
                if sandbox.status == "running" and not self.alive(sandbox):
                    self.halt(sandbox, db)
                    self.logger.info("sandbox container gone", extra={"sandbox_id": sandbox.id})
                elif startup and sandbox.status == "provisioning":
                    asyncio.get_running_loop().run_in_executor(None, self.boot, sandbox.id)

    async def watch(self, interval: int = 15):
        self.reconcile(startup=True)
        while True:
            await asyncio.sleep(interval)
            await asyncio.to_thread(self.reconcile)

    def _session(self, sandbox: Sandbox, user: User, channel: str, db: Querier) -> str:
        session = next((s for s in db.list_active_agent_sessions(sandbox_id=sandbox.id) if s.agent_type == channel), None)
        if session is None:
            session = db.create_agent_session(
                CreateAgentSessionParams(
                    id=str(uuid.uuid4()), sandbox_id=sandbox.id, created_by=user.id, agent_type=channel, config="{}"
                )
            )
        return session.id

    async def run_tool(self, user: User, sandbox_id: str, name: str, args: dict, channel: str) -> Any:
        tool = TOOLS.get(name)
        if tool is None:
            raise HTTPException(status_code=404, detail=f"unknown tool {name}")
        try:
            inspect.signature(tool.fn).bind("", **args)
        except TypeError as e:
            raise HTTPException(status_code=422, detail=str(e))
        with db_manager.session() as db:
            sandbox = self.allowed(sandbox_id, user, db, tool.permission, tool.action)
            allowed = KINDS.get(sandbox.kind)
            if allowed is not None and tool.category not in allowed:
                raise HTTPException(status_code=400, detail=f"{name} is not available in {sandbox.kind} sandboxes")
            execution = db.create_tool_execution(
                id=str(uuid.uuid4()),
                session_id=self._session(sandbox, user, channel, db),
                tool_name=name,
                input=json.dumps(args)[:4000],
            )
            db.update_tool_execution_status(status="running", id=execution.id)
        try:
            with tracer.start_as_current_span(
                f"tool {name}", attributes={"zoo.sandbox_id": sandbox.id, "zoo.channel": channel, "zoo.user_id": user.id}
            ):
                if inspect.iscoroutinefunction(tool.fn):
                    result = await tool.fn(sandbox.runtime_id, **args)
                else:
                    result = await asyncio.to_thread(tool.fn, sandbox.runtime_id, **args)
        except Exception as e:
            with db_manager.session() as db:
                db.fail_tool_execution(error_message=str(e)[:4000], id=execution.id)
            raise HTTPException(status_code=500, detail=str(e))
        with db_manager.session() as db:
            output = f"<{len(result)} bytes>" if name == "screenshot" else json.dumps(result, default=str)[:4000]
            db.complete_tool_execution(output=output, id=execution.id)
        return result

    async def proxy(self, websocket: WebSocket, sandbox_id: str, token: str = ""):
        with db_manager.session() as db:
            user = self.auth.user_from_token(token, db)
            sandbox = db.get_sandbox(id=sandbox_id)

        if user is None:
            await websocket.close(code=1008, reason="unauthorized")
            return
        if sandbox is None or sandbox.created_by != user.id or sandbox.status != "running" or not sandbox.access_url:
            await websocket.close(code=1008, reason="sandbox not available")
            return

        await websocket.accept()
        try:
            async with websockets.connect(sandbox.access_url, max_size=None) as target:
                tasks = [
                    asyncio.create_task(forward_client_to_target(websocket, target)),
                    asyncio.create_task(forward_target_to_client(target, websocket)),
                ]
                _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        except Exception as e:
            self.logger.error("sandbox proxy error", extra={"sandbox_id": sandbox_id, "error": repr(e)})
        finally:
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close()
