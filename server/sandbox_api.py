import asyncio
import uuid

import websockets
from fastapi import FastAPI, Depends, HTTPException, Response, WebSocket, BackgroundTasks
from pydantic import BaseModel, Field

from logger.logger import logger
from server.auth_api import AuthApi
from server.docker import IMAGE, run_container, wait_for_vnc, remove_container
from server.proxy import forward_client_to_target, forward_target_to_client
from server.schema import ClickRequestSchema, ExecRequest, ExecResponse
from server.tools import MoseTools, ObserveTools, ShellTools
from db.generated.query import (
    Querier,
    CreateSandboxParams,
    CreateSandboxImageParams,
    CreateSandboxImageVersionParams,
)
from db.generated.models import Sandbox, SandboxImageVersion, User
from db.connection import db_manager

IMAGE_SLUG = "zoo-sandbox"
IMAGE_VERSION = "latest"


class CreateSandboxRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)


class SandboxResponse(BaseModel):
    id: str
    name: str
    status: str
    error_message: str | None
    started_at: str | None
    created_at: str


class DeleteSandboxResponse(BaseModel):
    deleted: bool = True
    id: str


def to_response(sandbox: Sandbox) -> SandboxResponse:
    return SandboxResponse(
        id=sandbox.id,
        name=sandbox.name,
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
                sandbox, image_uri = self.create(payload, user, db)
            background.add_task(self.provision, sandbox.id, image_uri)
            return to_response(sandbox)

        @self.app.get("/sandboxes/{sandbox_id}", response_model=SandboxResponse)
        def get_sandbox(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> SandboxResponse:
            return to_response(self.owned(sandbox_id, user, db))

        @self.app.delete("/sandboxes/{sandbox_id}", response_model=DeleteSandboxResponse)
        def delete_sandbox(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> DeleteSandboxResponse:
            sandbox = self.owned(sandbox_id, user, db)
            if sandbox.runtime_id:
                remove_container(sandbox.runtime_id)
            db.soft_delete_sandbox(id=sandbox.id)
            self.logger.info("sandbox deleted", extra={"sandbox_id": sandbox.id})
            return DeleteSandboxResponse(id=sandbox.id)

        @self.app.post("/sandboxes/{sandbox_id}/screenshot")
        def screenshot(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ):
            sandbox = self.allowed(sandbox_id, user, db, "screen", "read")
            return Response(content=ObserveTools.screenshot(sandbox.runtime_id), media_type="image/png")

        @self.app.post("/sandboxes/{sandbox_id}/exec", response_model=ExecResponse)
        async def execute(
            sandbox_id: str,
            exec_req: ExecRequest,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ) -> ExecResponse:
            sandbox = self.allowed(sandbox_id, user, db, "shell", "exec")
            result = await ShellTools.execute_command(
                sandbox.runtime_id, command=exec_req.command, timeout=exec_req.timeout
            )
            return ExecResponse(sandbox_id=sandbox.id, **result)

        @self.app.post("/sandboxes/{sandbox_id}/click")
        def click(
            sandbox_id: str,
            click_req: ClickRequestSchema,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ):
            sandbox = self.allowed(sandbox_id, user, db, "input", "control")
            return MoseTools.click(sandbox.runtime_id, x=click_req.x, y=click_req.y, button=click_req.button)

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

    def _default_image_version(self, user: User, db: Querier) -> tuple[str, SandboxImageVersion]:
        slug = f"personal-{user.id}"
        workspace = db.get_workspace_by_slug(slug=slug)
        if workspace is None:
            workspace = db.create_workspace(id=str(uuid.uuid4()), name="Personal", slug=slug, created_by=user.id)
            db.add_workspace_member(workspace_id=workspace.id, user_id=user.id, role="owner")

        image = next((i for i in db.list_sandbox_images(workspace_id=workspace.id) if i.slug == IMAGE_SLUG), None)
        if image is None:
            image = db.create_sandbox_image(
                CreateSandboxImageParams(
                    id=str(uuid.uuid4()),
                    workspace_id=workspace.id,
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
        return workspace.id, version

    def create(self, payload: CreateSandboxRequest, user: User, db: Querier) -> tuple[Sandbox, str]:
        workspace_id, version = self._default_image_version(user, db)
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
                config="{}",
            )
        )
        if sandbox is None:
            raise HTTPException(status_code=500, detail="failed to create sandbox")
        sandbox = db.update_sandbox_status(status="provisioning", id=sandbox.id)
        self.logger.info("sandbox created", extra={"sandbox_id": sandbox.id, "user_id": user.id})
        return sandbox, version.image_uri

    def provision(self, sandbox_id: str, image_uri: str):
        try:
            container_id, host_port = run_container(f"zoo-sandbox-{sandbox_id}", image_uri)
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
                runtime_host="127.0.0.1",
                access_url=f"ws://127.0.0.1:{host_port}/websockify",
                id=sandbox_id,
            )

        ready = wait_for_vnc(host_port)
        with db_manager.session() as db:
            if not ready:
                db.set_sandbox_failed(error_message="desktop did not come up in time", id=sandbox_id)
                return
            if db.get_sandbox(id=sandbox_id).status != "deleted":
                db.set_sandbox_started(id=sandbox_id)
        self.logger.info("sandbox running", extra={"sandbox_id": sandbox_id, "host_port": host_port})

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
