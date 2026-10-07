import asyncio
import base64
import inspect
import json
import os
import time
import uuid
from typing import Any, Literal

import websockets
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db.connection import db_manager
from db.generated.models import Job, Sandbox, SandboxImageVersion, User
from db.generated.query import (
    CreateAgentSessionParams,
    CreateSandboxImageParams,
    CreateSandboxImageVersionParams,
    CreateSandboxParams,
    Querier,
)
from logger.logger import logger
from server import macos, objects, tickets, windows
from server.auth_api import AuthApi, personal_workspace
from server.docker import IMAGE, copy_volume, default_image, run_container, wait_for_vnc, write_secrets
from server.executions import ExecutionLog
from server.guest import TUNNEL_URL, VNC_PORT, Terminal, Tunnel, guest_env, hub
from server.images import MEDIA_TYPES
from server.jobs import WAITING, Jobs
from server.platforms import PLATFORMS, os_of, parse
from server.pool import Pool
from server.proxy import forward_client_to_target, forward_target_to_client
from server.registry import KINDS, TOOLS, open_url
from server.runtime import (
    VMS,
    authenticated_channel,
    connect,
    export_home,
    import_dir,
    import_home,
    is_running,
    is_vm,
    remove_container,
    remove_volume,
)
from server.schema import ExecRequest, ExecResponse
from server.security import (
    audit,
    decrypt_bytes,
    enforce,
    ensure_vnc_password,
    forget_secrets,
    redact,
    redaction_values,
    remember_secrets,
    secret_env,
    vnc_password,
)
from server.telemetry import tracer
from server.vnc import NO_AUTH, VERSION, Buffered, authenticate_async

IMAGE_SLUG = "zoo-sandbox"
IMAGE_VERSION = "latest"
AUTO = "auto"
PLATFORM_NAMES = {"macos": "macOS", "windows": "Windows"}
PROFILE_DIR = os.environ.get("PROFILE_DIR", "data/profiles")
# where each app keeps its profile, under the sandbox user's home, per OS
PROFILE_APPS = {
    "linux": {
        "firefox": ".mozilla",
        "chromium": ".config/chromium",
        "chrome": ".config/google-chrome",
        "vscode": ".config/Code",
    },
    "macos": {
        # Safari's data is behind Full Disk Access (macos/README.md)
        "safari": "Library/Containers/com.apple.Safari",
        "chrome": "Library/Application Support/Google/Chrome",
        "edge": "Library/Application Support/Microsoft Edge",
        "firefox": "Library/Application Support/Firefox",
        "vscode": "Library/Application Support/Code",
    },
    "windows": {
        "chrome": "AppData/Local/Google/Chrome/User Data",
        "edge": "AppData/Local/Microsoft/Edge/User Data",
        "firefox": "AppData/Roaming/Mozilla/Firefox",
        "vscode": "AppData/Roaming/Code",
    },
}
PROFILE_HOMES = {"linux": "/home/zoo", "macos": macos.HOME, "windows": windows.HOME}


def platform_of(kind: str) -> str:
    return kind if kind in VMS else "linux"


def profile_path(platform: str, app: str) -> str:
    return f"{PROFILE_HOMES[platform]}/{PROFILE_APPS[platform][app]}"


BROWSER_HOME = os.environ.get("ZOO_BROWSER_HOME", "https://duckduckgo.com")
# how long a boot may take, retries included, before the sandbox fails
BOOT_DEADLINE = {"linux": 3 * 60, "vm": 10 * 60}
# a macOS or Windows VM that neither draws nor sends its guest heartbeat for this long is restarted
HANG_SECONDS = 60


def boot_deadline(kind: str) -> int:
    return BOOT_DEADLINE["vm" if kind in VMS else "linux"]


async def offer_no_auth(websocket: WebSocket) -> bytes:
    """Plays the VNC server's side of the handshake to the browser, offering no auth because the API has already
    authenticated upstream. Returns what the browser sent past it (its ClientInit) for the caller to pass on."""

    async def receive() -> bytes:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise ConnectionError("viewer disconnected")
        return message.get("bytes") or (message.get("text") or "").encode()

    viewer = Buffered(receive)
    await websocket.send_bytes(VERSION)
    await viewer.read(12)
    await websocket.send_bytes(bytes([1, NO_AUTH]))
    await viewer.read(1)
    await websocket.send_bytes((0).to_bytes(4, "big"))
    return viewer.data


class CreateSandboxRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    kind: Literal["desktop", "browser", "code", "macos", "windows"] = "desktop"
    server_id: str | None = None
    profile_ids: list[str] = []
    secret_ids: list[str] = []
    # macOS only: the guest user keeps admin rights and passwordless sudo, so an agent can undo the VM's own policy
    admin: bool = False
    # macOS only: when every Mac already runs Apple's limit of 2 macOS VMs, wait in the queue for one to stop
    # instead of failing with "Mac full"
    queue: bool = True


class MoveSandboxRequest(BaseModel):
    server_id: str | None = None


class JobResponse(BaseModel):
    kind: str
    state: str
    attempts: int
    max_attempts: int
    last_error: str | None
    deadline: str | None
    # waiting for room (a full Mac) rather than retrying after an error; last_error says what it waits for
    waiting: bool = False


class SandboxResponse(BaseModel):
    id: str
    name: str
    kind: str
    server_id: str | None
    status: str
    error_message: str | None
    started_at: str | None
    created_at: str
    # the runtime host didn't answer the last health check; the sandbox may still be fine
    unreachable: bool = False
    # the boot, stop, delete or move in progress, if any
    job: JobResponse | None = None
    # the image a Linux sandbox boots from; it stays on it across upgrades until restarted on the new one
    image: str | None = None
    image_outdated: bool = False
    # macOS and Windows: the base VM version it was cloned from, how long its last boot took, and when the API last restarted
    # it because it hung (no screen updates and no guest heartbeat)
    base_version: str | None = None
    boot_seconds: float | None = None
    recovered_at: str | None = None


class ToolExecutionResponse(BaseModel):
    id: str
    tool_name: str
    status: str
    input: str
    error_message: str | None
    created_at: str
    completed_at: str | None


class VncTicketResponse(BaseModel):
    ticket: str
    expires_in: int = tickets.TICKET_TTL


class DeleteSandboxResponse(BaseModel):
    deleted: bool = True
    id: str


def pinned_image(sandbox: Sandbox) -> str | None:
    """The default image this sandbox first booted from, or None if it hasn't booted or runs a custom image."""
    return json.loads(sandbox.config or "{}").get("image")


def to_response(sandbox: Sandbox, db: Querier | None = None) -> SandboxResponse:
    job = db.get_active_job(sandbox_id=sandbox.id) if db is not None else None
    image = pinned_image(sandbox)
    return SandboxResponse(
        id=sandbox.id,
        name=sandbox.name,
        kind=sandbox.kind,
        server_id=sandbox.server_id,
        status=sandbox.status,
        error_message=sandbox.error_message,
        started_at=sandbox.started_at,
        created_at=sandbox.created_at,
        unreachable=sandbox.unreachable_since is not None,
        job=JobResponse(
            **{k: getattr(job, k) for k in JobResponse.model_fields if k != "waiting"},
            waiting=(job.last_error or "").startswith(WAITING),
        )
        if job
        else None,
        image=image,
        image_outdated=image is not None and image != default_image(sandbox.kind),
        base_version=sandbox.base_version,
        boot_seconds=sandbox.boot_seconds,
        recovered_at=sandbox.recovered_at,
    )


class SandboxApi:
    def __init__(self, app: FastAPI, auth: AuthApi):
        self.logger = logger
        self.app = app
        self.auth = auth
        self.jobs = Jobs()
        # macOS sandbox id -> when it was first found hung, and when its screen was last checked
        self.suspects: dict[str, float] = {}
        self.probed: dict[str, float] = {}
        self.pool = Pool()
        self.executions = ExecutionLog()
        self.jobs.register("boot", self.boot, attempts=3, backoff=(5, 15), failed=self.boot_failed)
        self.jobs.register("stop", self.stop, attempts=3, backoff=(5, 15), failed=self.lifecycle_failed("stop"))
        self.jobs.register(
            "delete", self.delete, attempts=5, backoff=(10, 30, 60, 120), failed=self.lifecycle_failed("delete")
        )
        self.jobs.register("move", self.move, attempts=2, backoff=(30,), failed=self.lifecycle_failed("move"))
        self._register_routes()

    def _register_routes(self):
        current_user = self.auth.current_user

        @self.app.get("/sandboxes", response_model=list[SandboxResponse])
        def list_sandboxes(
            user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[SandboxResponse]:
            return [to_response(s, db) for s in db.list_sandboxes_by_user(created_by=user.id)]

        @self.app.post("/sandboxes", response_model=SandboxResponse, status_code=201)
        def create_sandbox(payload: CreateSandboxRequest, user: User = Depends(current_user)) -> SandboxResponse:
            with db_manager.session() as db:
                sandbox = self.create(payload, user, db)
                response = to_response(sandbox, db)
            self.jobs.kick()
            return response

        @self.app.get("/sandboxes/{sandbox_id}", response_model=SandboxResponse)
        def get_sandbox(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> SandboxResponse:
            return to_response(self.owned(sandbox_id, user, db), db)

        @self.app.post("/sandboxes/{sandbox_id}/start", response_model=SandboxResponse)
        def start_sandbox(sandbox_id: str, user: User = Depends(current_user)) -> SandboxResponse:
            with db_manager.session() as db:
                sandbox = self.idle(sandbox_id, user, db)
                if sandbox.status in ("running", "provisioning"):
                    raise HTTPException(status_code=409, detail=f"sandbox is {sandbox.status}")
                sandbox = db.update_sandbox_status(status="provisioning", id=sandbox.id)
                self.jobs.enqueue(db, sandbox.id, "boot", boot_deadline(sandbox.kind))
                response = to_response(sandbox, db)
            self.jobs.kick()
            return response

        @self.app.post("/sandboxes/{sandbox_id}/stop", response_model=SandboxResponse)
        def stop_sandbox(sandbox_id: str, user: User = Depends(current_user)) -> SandboxResponse:
            with db_manager.session() as db:
                sandbox = self.owned(sandbox_id, user, db)
                active = db.get_active_job(sandbox_id=sandbox.id)
                if active is not None and active.kind in ("stop", "delete"):
                    raise HTTPException(status_code=409, detail=f"sandbox is busy: {active.kind} in progress")
                # a boot that hasn't started yet is dropped; one already running finishes first, then this stops it
                db.cancel_sandbox_jobs(sandbox_id=sandbox.id)
                self.jobs.enqueue(db, sandbox.id, "stop")
                response = to_response(sandbox, db)
            self.jobs.kick()
            return response

        @self.app.post("/sandboxes/{sandbox_id}/upgrade", response_model=SandboxResponse)
        def upgrade_sandbox(sandbox_id: str, user: User = Depends(current_user)) -> SandboxResponse:
            """Restarts the sandbox on the current default image. Its home volume is kept."""
            with db_manager.session() as db:
                sandbox = self.idle(sandbox_id, user, db)
                if pinned_image(sandbox) is None:
                    raise HTTPException(status_code=400, detail="this sandbox doesn't run the default image")
                if sandbox.status not in ("running", "stopped", "failed"):
                    raise HTTPException(status_code=409, detail=f"sandbox is {sandbox.status}")
                config = {**json.loads(sandbox.config or "{}"), "image": default_image(sandbox.kind)}
                db.update_sandbox(
                    name=sandbox.name, resources=sandbox.resources, config=json.dumps(config), id=sandbox.id
                )
                if sandbox.status == "running":
                    self.jobs.enqueue(db, sandbox.id, "stop", restart=True)
                else:
                    db.update_sandbox_status(status="provisioning", id=sandbox.id)
                    self.jobs.enqueue(db, sandbox.id, "boot", boot_deadline(sandbox.kind))
                response = to_response(self.owned(sandbox.id, user, db), db)
            self.jobs.kick()
            return response

        @self.app.delete("/sandboxes/{sandbox_id}", response_model=DeleteSandboxResponse)
        def delete_sandbox(sandbox_id: str, user: User = Depends(current_user)) -> DeleteSandboxResponse:
            with db_manager.session() as db:
                sandbox = self.owned(sandbox_id, user, db)
                active = db.get_active_job(sandbox_id=sandbox.id)
                if active is None or active.kind != "delete":
                    db.cancel_sandbox_jobs(sandbox_id=sandbox.id)
                    db.update_sandbox_status(status="deleting", id=sandbox.id)
                    self.jobs.enqueue(db, sandbox.id, "delete")
            self.jobs.kick()
            return DeleteSandboxResponse(id=sandbox.id)

        @self.app.post("/sandboxes/{sandbox_id}/move", response_model=SandboxResponse)
        def move_sandbox(
            sandbox_id: str, payload: MoveSandboxRequest, user: User = Depends(current_user)
        ) -> SandboxResponse:
            with db_manager.session() as db:
                sandbox = self.idle(sandbox_id, user, db)
                if sandbox.status in ("running", "provisioning"):
                    raise HTTPException(status_code=409, detail="stop the sandbox before moving it")
                if sandbox.kind in VMS and not objects.configured():
                    raise HTTPException(
                        status_code=409,
                        detail=f"moving {PLATFORM_NAMES[sandbox.kind]} sandboxes between servers needs ZOO_OBJECT_STORE",
                    )
                target = self.place(payload.server_id, user, db, sandbox.kind)
                if target != sandbox.server_id:
                    self.jobs.enqueue(db, sandbox.id, "move", target=target)
                response = to_response(sandbox, db)
            self.jobs.kick()
            return response

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
        async def screenshot(
            sandbox_id: str,
            format: Literal["png", "webp", "jpeg"] = "png",
            scale: float = 1.0,
            quality: int = 80,
            user: User = Depends(current_user),
        ):
            args = {"format": format, "scale": scale, "quality": quality}
            data = await self.run_tool(user, sandbox_id, "screenshot", args, "api")
            return Response(content=base64.b64decode(data), media_type=MEDIA_TYPES[format])

        @self.app.post("/sandboxes/{sandbox_id}/exec", response_model=ExecResponse)
        async def execute(sandbox_id: str, exec_req: ExecRequest, user: User = Depends(current_user)) -> ExecResponse:
            result = await self.run_tool(user, sandbox_id, "execute_command", exec_req.model_dump(), "api")
            return ExecResponse(sandbox_id=sandbox_id, **result)

        @self.app.get("/sandboxes/{sandbox_id}/guest")
        def guest_status(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> dict:
            return hub.status(self.owned(sandbox_id, user, db).id)

        @self.app.get("/sandboxes/{sandbox_id}/executions", response_model=list[ToolExecutionResponse])
        def list_executions(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[ToolExecutionResponse]:
            sandbox = self.owned(sandbox_id, user, db)
            self.executions.flush()
            return [
                ToolExecutionResponse(**{k: getattr(e, k) for k in ToolExecutionResponse.model_fields})
                for e in db.list_tool_executions_by_sandbox(sandbox_id=sandbox.id, limit=100)
            ]

        @self.app.get("/sandboxes/{sandbox_id}/backup")
        def backup(sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)):
            sandbox = self.running(sandbox_id, user, db)
            return StreamingResponse(
                export_home(sandbox.runtime_id),
                media_type="application/x-tar",
                headers={"Content-Disposition": f'attachment; filename="{sandbox.name}.tar"'},
            )

        @self.app.post("/sandboxes/{sandbox_id}/restore", response_model=SandboxResponse)
        async def restore(sandbox_id: str, request: Request, user: User = Depends(current_user)) -> SandboxResponse:
            with db_manager.session() as db:
                sandbox = self.running(sandbox_id, user, db)
            await asyncio.to_thread(import_home, sandbox.runtime_id, await request.body())
            return to_response(sandbox)

        @self.app.post("/sandboxes/{sandbox_id}/vnc-ticket", response_model=VncTicketResponse)
        def vnc_ticket(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> VncTicketResponse:
            sandbox = self.running(sandbox_id, user, db)
            if not sandbox.access_url:
                raise HTTPException(status_code=400, detail="this sandbox has no screen")
            return VncTicketResponse(ticket=tickets.issue(user.id, f"sandbox:{sandbox.id}"))

        self.app.websocket("/sandboxes/{sandbox_id}/ws")(self.proxy)
        self.app.websocket("/guest/connect")(hub.serve)

        @self.app.post("/sandboxes/{sandbox_id}/terminal-ticket", response_model=VncTicketResponse)
        def terminal_ticket(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> VncTicketResponse:
            sandbox = self.allowed(sandbox_id, user, db, "shell", "exec")
            guest = hub.for_sandbox(sandbox.id)
            if guest is None or not guest.has("pty"):
                raise HTTPException(
                    status_code=409, detail="the terminal needs the sandbox's guest agent; restart the sandbox"
                )
            return VncTicketResponse(ticket=tickets.issue(user.id, f"terminal:{sandbox.id}"))

        self.app.websocket("/sandboxes/{sandbox_id}/terminal")(self.terminal)

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

    def idle(self, sandbox_id: str, user: User, db: Querier) -> Sandbox:
        """An owned sandbox with no boot, stop, delete or move in progress."""
        sandbox = self.owned(sandbox_id, user, db)
        active = db.get_active_job(sandbox_id=sandbox.id)
        if active is not None:
            raise HTTPException(status_code=409, detail=f"sandbox is busy: {active.kind} in progress")
        return sandbox

    def running(self, sandbox_id: str, user: User, db: Querier) -> Sandbox:
        sandbox = self.owned(sandbox_id, user, db)
        if sandbox.status != "running" or not sandbox.runtime_id:
            raise HTTPException(status_code=409, detail=f"sandbox is {sandbox.status}")
        return sandbox

    def server_of(self, sandbox: Sandbox, db: Querier):
        return db.get_server(id=sandbox.server_id) if sandbox.server_id else None

    def place(
        self, server_id: str | None, user: User, db: Querier, kind: str = "desktop", queue: bool = False
    ) -> str | None:
        platform = os_of(kind)
        if platform == "macos":
            macos.ensure_local_server(user.id, db)
        servers = [s for s in db.list_servers_by_user(created_by=user.id) if platform in parse(s.capabilities)]
        if platform in VMS:
            return self.place_vm(platform, server_id, servers, db, queue)
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

    def place_vm(self, platform: str, server_id: str | None, servers: list, db: Querier, queue: bool = False) -> str:
        name, limit = PLATFORM_NAMES[platform], VMS[platform].MAX_VMS
        if not servers:
            raise HTTPException(
                status_code=400, detail=f"add a {PLATFORMS[platform].host} under Servers to run {name} sandboxes"
            )
        if server_id is not None and server_id != AUTO:
            if server_id not in {s.id for s in servers}:
                raise HTTPException(status_code=404, detail=f"{name} server not found")
            return server_id
        load = {s.id: 0 for s in servers}
        for sb in db.list_all_sandboxes():
            if sb.server_id in load and sb.status in ("running", "provisioning"):
                load[sb.server_id] += 1
        best = min(load, key=load.get)
        if load[best] >= limit:
            if platform == "macos" and queue:
                # it boots when a VM on that Mac stops (macos.start waits in the job queue)
                return best
            if platform == "macos":
                raise HTTPException(
                    status_code=409,
                    detail=f"Mac full: every Mac already runs {limit} macOS VMs, the most Apple allows per Mac. "
                    "Stop one, add a Mac, or create with queue to wait for room",
                )
            raise HTTPException(status_code=409, detail=f"every {name} server already runs {limit} VMs")
        return best

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
        if payload.admin and payload.kind != "macos":
            raise HTTPException(status_code=400, detail="admin sandboxes are for macOS")
        server_id = self.place(payload.server_id, user, db, payload.kind, payload.queue)
        for profile_id in payload.profile_ids:
            profile = db.get_profile(id=profile_id)
            if profile is None or profile.user_id != user.id:
                raise HTTPException(status_code=404, detail="profile not found")
            if profile.platform != platform_of(payload.kind):
                raise HTTPException(
                    status_code=400, detail=f"profile {profile.name} is from a {profile.platform} sandbox"
                )
        for secret_id in payload.secret_ids:
            secret = db.get_vault_secret(id=secret_id)
            if secret is None or secret.user_id != user.id:
                raise HTTPException(status_code=404, detail="secret not found")
        # a warm one takes the pooled container's id, which its name, volume and guest token already carry
        pooled = self.pool.claim(db, payload.kind, server_id)
        sandbox_id = pooled.id if pooled else str(uuid.uuid4())
        config: dict[str, Any] = {"profiles": payload.profile_ids}
        if payload.admin:
            config["admin"] = True
        if pooled is not None:
            config = {**json.loads(pooled.config), **config, "image": pooled.image, "pooled": True}
        sandbox = db.create_sandbox(
            CreateSandboxParams(
                id=sandbox_id,
                workspace_id=workspace_id,
                image_version_id=version.id,
                created_by=user.id,
                name=payload.name or f"sandbox-{sandbox_id[:8]}",
                runtime=payload.kind if payload.kind in VMS else "docker",
                resources="{}",
                config=json.dumps(config),
            )
        )
        if sandbox is None:
            raise HTTPException(status_code=500, detail="failed to create sandbox")
        if pooled is not None:
            db.update_sandbox_runtime(
                runtime_id=pooled.runtime_id,
                runtime_host=pooled.runtime_host,
                access_url=pooled.access_url,
                id=sandbox.id,
            )
        db.set_sandbox_placement(server_id=server_id, kind=payload.kind, id=sandbox.id)
        for secret_id in dict.fromkeys(payload.secret_ids):
            db.attach_vault_secret(sandbox_id=sandbox.id, secret_id=secret_id)
            name = db.get_vault_secret(id=secret_id).name
            audit(db, user, "secret.attach", "secret", secret_id, sandbox.id, name=name, sandbox=sandbox.name)
        sandbox = db.update_sandbox_status(status="provisioning", id=sandbox.id)
        # the caller kicks the queue once this transaction commits
        self.jobs.enqueue(db, sandbox.id, "boot", boot_deadline(sandbox.kind))
        self.logger.info("sandbox created", extra={"sandbox_id": sandbox.id, "user_id": user.id})
        return sandbox

    def halt(self, sandbox: Sandbox, db: Querier) -> Sandbox:
        if sandbox.runtime_id:
            remove_container(sandbox.runtime_id)
        db.clear_sandbox_runtime(id=sandbox.id)
        db.set_sandbox_reachable(id=sandbox.id)
        return db.set_sandbox_stopped(id=sandbox.id)

    # Jobs. Each one may run again after a failure or a restart, so each step is safe to repeat.

    def boot(self, job: Job):
        sandbox_id = job.sandbox_id
        with db_manager.session() as db:
            sandbox = db.get_sandbox(id=sandbox_id)
            if sandbox is None or sandbox.status != "provisioning":
                return
            version = db.get_sandbox_image_version(id=sandbox.image_version_id)
            if version is None:
                raise RuntimeError("the sandbox's image version is missing")
            default = version.version == IMAGE_VERSION and db.get_sandbox_image(id=version.image_id).slug == IMAGE_SLUG
            env = secrets = secret_env(sandbox, db)
            server = self.server_of(sandbox, db)
            desktop = sandbox.kind != "code"
            if desktop and sandbox.kind not in VMS:
                env = {**env, "ZOO_VNC_PASSWORD": ensure_vnc_password(sandbox, db)}
            if sandbox.kind not in VMS:
                env = {**env, **guest_env(sandbox.id, remote=server is not None)}
            if sandbox.kind in VMS:
                image = ""
            elif default or not desktop:
                image = self.pin_image(sandbox.id, db)
            else:
                image = version.image_uri
            profiles = [db.get_profile(id=p) for p in json.loads(sandbox.config or "{}").get("profiles", [])]
            remember_secrets(sandbox_id, [*env.values(), vnc_password(sandbox)])
        if sandbox.kind in VMS:
            admin = bool(json.loads(sandbox.config or "{}").get("admin"))
            return self.boot_vm(job, sandbox.kind, server, env, profiles, admin)
        if self.warm(sandbox):
            return self.adopt(job, sandbox, secrets, profiles)
        # the container is named after the sandbox, so a retry adopts the one an earlier attempt started
        container_id, host, port = run_container(f"zoo-sandbox-{sandbox_id}", image, sandbox_id, env, server, desktop)
        if container_id is not None:
            hub.bind(container_id, sandbox_id)
        tunneled = desktop and port is None
        access_url = TUNNEL_URL if tunneled else f"ws://{host}:{port}/websockify" if desktop else None
        if not self.record_runtime(job, container_id, host, access_url):
            return
        for profile in profiles:
            if profile is not None:
                self.apply_profile(container_id, profile)
        if desktop and not (hub.wait_for_vnc(sandbox_id) if tunneled else wait_for_vnc(host, port)):
            raise RuntimeError("desktop did not come up in time")
        sandbox = self.mark_started(job)
        if sandbox is not None and sandbox.kind == "browser":
            try:
                open_url(container_id, BROWSER_HOME)
            except Exception as e:
                self.logger.error("browser launch failed", extra={"sandbox_id": sandbox_id, "error": str(e)})

    def warm(self, sandbox: Sandbox) -> bool:
        """Whether the sandbox was claimed from the pool and its pooled container is still up."""
        if not (json.loads(sandbox.config or "{}").get("pooled") and sandbox.runtime_id):
            return False
        try:
            if is_running(sandbox.runtime_id):
                return True
            remove_container(sandbox.runtime_id)
        except Exception as e:
            self.logger.warning("pooled container lost", extra={"sandbox_id": sandbox.id, "error": str(e)})
        return False

    def adopt(self, job: Job, sandbox: Sandbox, secrets: dict[str, str], profiles: list):
        """Finishes a boot on a container from the warm pool, which is already up: only the owner's parts are left."""
        if secrets:
            write_secrets(sandbox.runtime_id, secrets)
        for profile in profiles:
            if profile is not None:
                self.apply_profile(sandbox.runtime_id, profile)
        started = self.mark_started(job)
        if started is not None and started.kind == "browser":
            try:
                open_url(sandbox.runtime_id, BROWSER_HOME)
            except Exception as e:
                self.logger.error("browser launch failed", extra={"sandbox_id": sandbox.id, "error": str(e)})

    def pin_image(self, sandbox_id: str, db: Querier) -> str:
        """The image the sandbox boots from: the default image of its first boot, so upgrading Zoo doesn't swap
        the image under an existing sandbox. POST /sandboxes/{id}/upgrade moves it to the current one."""
        # read again: ensure_vnc_password may have just rewritten the config
        sandbox = db.get_sandbox(id=sandbox_id)
        if sandbox is None:
            raise RuntimeError(f"sandbox {sandbox_id} is gone")
        config = json.loads(sandbox.config or "{}")
        if "image" not in config:
            config["image"] = default_image(sandbox.kind)
            db.update_sandbox(name=sandbox.name, resources=sandbox.resources, config=json.dumps(config), id=sandbox.id)
        return config["image"]

    def boot_vm(self, job: Job, kind: str, server, env: dict[str, str], profiles: list, admin: bool):
        name = PLATFORM_NAMES[kind]
        if server is None:
            raise RuntimeError(f"{name} sandboxes need a {name} server")
        options = {"admin": admin} if kind == "macos" else {}
        started = time.monotonic()
        runtime_id, access_url = VMS[kind].start(job.sandbox_id, server, env, **options)
        seconds = round(time.monotonic() - started, 1)
        if self.record_runtime(job, runtime_id, server.bind_address, access_url):
            with db_manager.session() as db:
                db.set_sandbox_boot(base_version=VMS[kind].base_of(runtime_id), boot_seconds=seconds, id=job.sandbox_id)
            self.logger.info(f"{name} VM booted", extra={"sandbox_id": job.sandbox_id, "boot_seconds": seconds})
            for profile in profiles:
                if profile is not None:
                    self.apply_profile(runtime_id, profile)
            self.mark_started(job)

    def still_booting(self, job: Job, db: Querier) -> Sandbox | None:
        """The sandbox, if this boot still owns it: not stopped, deleted or timed out meanwhile."""
        sandbox = db.get_sandbox(id=job.sandbox_id)
        if sandbox is None or sandbox.status != "provisioning" or not self.jobs.owns(job):
            return None
        return sandbox

    def record_runtime(self, job: Job, runtime_id: str, host: str | None, access_url: str | None) -> bool:
        with db_manager.session() as db:
            sandbox = self.still_booting(job, db)
            if sandbox is not None:
                db.update_sandbox_runtime(
                    runtime_id=runtime_id, runtime_host=host, access_url=access_url, id=sandbox.id
                )
                return True
        remove_container(runtime_id)
        return False

    def mark_started(self, job: Job) -> Sandbox | None:
        with db_manager.session() as db:
            if self.still_booting(job, db) is None:
                return None
            sandbox = db.set_sandbox_started(id=job.sandbox_id)
            db.set_sandbox_reachable(id=sandbox.id)
            try:
                enforce(sandbox, db)
            except Exception as e:
                self.logger.error("policy enforcement failed", extra={"sandbox_id": sandbox.id, "error": str(e)})
        self.logger.info("sandbox running", extra={"sandbox_id": sandbox.id, "server_id": sandbox.server_id})
        return sandbox

    def boot_failed(self, job: Job, error: str):
        with db_manager.session() as db:
            sandbox = db.get_sandbox(id=job.sandbox_id)
        if sandbox is None or sandbox.status != "provisioning":
            return
        if sandbox.runtime_id:
            try:
                remove_container(sandbox.runtime_id)
            except Exception as e:
                self.logger.error("cleanup after failed boot failed", extra={"sandbox_id": sandbox.id, "error": str(e)})
        with db_manager.session() as db:
            db.clear_sandbox_runtime(id=sandbox.id)
            db.set_sandbox_failed(error_message=error, id=sandbox.id)

    def lifecycle_failed(self, kind: str):
        def failed(job: Job, error: str):
            with db_manager.session() as db:
                sandbox = db.get_sandbox(id=job.sandbox_id)
                if sandbox is not None and sandbox.status != "deleted":
                    db.set_sandbox_failed(error_message=f"{kind} failed: {error}", id=sandbox.id)

        return failed

    def stop(self, job: Job):
        with db_manager.session() as db:
            sandbox = db.get_sandbox(id=job.sandbox_id)
        if sandbox is None or sandbox.status == "deleted":
            return
        if sandbox.runtime_id:
            remove_container(sandbox.runtime_id)
        forget_secrets(sandbox.id)
        with db_manager.session() as db:
            db.clear_sandbox_runtime(id=sandbox.id)
            db.set_sandbox_reachable(id=sandbox.id)
            db.set_sandbox_stopped(id=sandbox.id)
            if json.loads(job.args).get("restart"):
                db.update_sandbox_status(status="provisioning", id=sandbox.id)
                self.jobs.enqueue(db, sandbox.id, "boot", boot_deadline(sandbox.kind))

    def delete(self, job: Job):
        with db_manager.session() as db:
            sandbox = db.get_sandbox(id=job.sandbox_id)
            if sandbox is None or sandbox.status == "deleted":
                return
            server = self.server_of(sandbox, db)
        if sandbox.runtime_id:
            remove_container(sandbox.runtime_id)
        remove_volume(sandbox, server)
        forget_secrets(sandbox.id)
        with db_manager.session() as db:
            db.soft_delete_sandbox(id=sandbox.id)
        self.logger.info("sandbox deleted", extra={"sandbox_id": sandbox.id})

    def move(self, job: Job):
        target = json.loads(job.args)["target"]
        with db_manager.session() as db:
            sandbox = db.get_sandbox(id=job.sandbox_id)
            if sandbox is None or sandbox.status in ("running", "provisioning", "deleting", "deleted"):
                return
            source = self.server_of(sandbox, db)
            dest = db.get_server(id=target) if target else None
        if sandbox.kind in VMS:
            VMS[sandbox.kind].move(sandbox.id, source, dest)
        else:
            copy_volume(sandbox.id, source, dest)
        with db_manager.session() as db:
            db.set_sandbox_placement(server_id=target, kind=sandbox.kind, id=sandbox.id)

    def apply_profile(self, container_id: str, profile):
        parent = os.path.dirname(profile_path(profile.platform, profile.app))
        with open(os.path.join(PROFILE_DIR, f"{profile.id}.tar"), "rb") as f:
            data = f.read()
        if profile.encrypted:
            data = decrypt_bytes(data)
        import_dir(container_id, parent, data)

    def alive(self, sandbox: Sandbox) -> bool | None:
        """Whether the sandbox's runtime is running, or None when its host couldn't be asked."""
        if not sandbox.runtime_id:
            return False
        try:
            return is_running(sandbox.runtime_id)
        except Exception as e:
            self.logger.warning("sandbox host unreachable", extra={"sandbox_id": sandbox.id, "error": str(e)})
            return None

    def reconcile(self, startup: bool = False):
        with db_manager.session() as db:
            if startup:
                for server in db.list_all_servers():
                    try:
                        connect(server)
                    except Exception as e:
                        self.logger.error("server unreachable", extra={"server_id": server.id, "error": str(e)})
            sandboxes = [s for s in list(db.list_all_sandboxes()) if db.get_active_job(sandbox_id=s.id) is None]
            if startup:
                # sandboxes left mid-boot or mid-delete by a version without the job queue
                for sandbox in sandboxes:
                    if sandbox.status == "provisioning":
                        self.jobs.enqueue(db, sandbox.id, "boot", boot_deadline(sandbox.kind))
                    elif sandbox.status == "deleting":
                        self.jobs.enqueue(db, sandbox.id, "delete")
        if startup:
            self.jobs.kick()
        for sandbox in sandboxes:
            if sandbox.status != "running":
                continue
            alive = self.alive(sandbox)
            # outside the session: the screen check can take a while
            hung = alive is True and self.hung(sandbox)
            with db_manager.session() as db:
                current = db.get_sandbox(id=sandbox.id)
                if current.status != "running" or current.runtime_id != sandbox.runtime_id:
                    continue
                if alive is None:
                    db.set_sandbox_unreachable(id=sandbox.id)
                elif alive:
                    db.set_sandbox_reachable(id=sandbox.id)
                    if hung and db.get_active_job(sandbox_id=sandbox.id) is None:
                        db.set_sandbox_recovered(id=sandbox.id)
                        self.jobs.enqueue(db, sandbox.id, "stop", restart=True)
                        self.suspects.pop(sandbox.id, None)
                        self.logger.warning("VM hung, restarting it", extra={"sandbox_id": sandbox.id})
                elif db.get_active_job(sandbox_id=sandbox.id) is None:
                    self.halt(current, db)
                    self.logger.info("sandbox container gone", extra={"sandbox_id": sandbox.id})

    def hung(self, sandbox: Sandbox) -> bool:
        """Whether a running macOS or Windows VM has hung: its guest went quiet (no heartbeat) and its screen stopped
        answering, on checks HANG_SECONDS apart. Without a heartbeat (a VM with no guest) the screen is checked at most
        every half HANG_SECONDS."""
        if sandbox.kind not in VMS:
            return False
        now = time.monotonic()
        if hub.heartbeat(sandbox.id):
            self.suspects.pop(sandbox.id, None)
            return False
        if sandbox.id not in self.suspects and now - self.probed.get(sandbox.id, 0) < HANG_SECONDS / 2:
            return False
        self.probed[sandbox.id] = now
        if VMS[sandbox.kind].responsive(sandbox.runtime_id or ""):
            self.suspects.pop(sandbox.id, None)
            return False
        return now - self.suspects.setdefault(sandbox.id, now) >= HANG_SECONDS

    async def watch(self, interval: int = 15):
        await asyncio.to_thread(self.reconcile, True)
        while True:
            await asyncio.sleep(interval)
            await asyncio.to_thread(self.reconcile)

    def _session(self, sandbox: Sandbox, user: User, channel: str, db: Querier) -> str:
        session = next(
            (s for s in db.list_active_agent_sessions(sandbox_id=sandbox.id) if s.agent_type == channel), None
        )
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
            # docker exec sessions see the container env, which carries the x11vnc password
            secrets = redaction_values(sandbox, db)
        execution_id = str(uuid.uuid4())

        def started(db: Querier):
            db.create_tool_execution(
                id=execution_id,
                session_id=self._session(sandbox, user, channel, db),
                tool_name=name,
                input=json.dumps(args)[:4000],
            )
            db.update_tool_execution_status(status="running", id=execution_id)

        self.executions.write(started)
        try:
            with tracer.start_as_current_span(
                f"tool {name}",
                attributes={"zoo.sandbox_id": sandbox.id, "zoo.channel": channel, "zoo.user_id": user.id},
            ):
                fn = tool.impl(sandbox.runtime_id)
                if inspect.iscoroutinefunction(fn):
                    result = await fn(sandbox.runtime_id, **args)
                else:
                    result = await asyncio.to_thread(fn, sandbox.runtime_id, **args)
        except Exception as e:
            error = redact(str(e), secrets)
            self.executions.write(lambda db: db.fail_tool_execution(error_message=error[:4000], id=execution_id))
            raise HTTPException(status_code=500, detail=error)
        result = redact(result, secrets)
        if name == "screenshot":
            output = f"<{len(result)} bytes>"
        elif name == "screen_diff" and result.get("image"):
            output = json.dumps({**result, "image": f"<{len(result['image'])} bytes>"}, default=str)
        else:
            output = json.dumps(result, default=str)[:4000]
        self.executions.write(lambda db: db.complete_tool_execution(output=output, id=execution_id))
        return result

    async def proxy(self, websocket: WebSocket, sandbox_id: str, ticket: str = ""):
        user_id = tickets.redeem(ticket, f"sandbox:{sandbox_id}")
        if user_id is None:
            await websocket.close(code=1008, reason="unauthorized")
            return
        with db_manager.session() as db:
            sandbox = db.get_sandbox(id=sandbox_id)
        if sandbox is None or sandbox.created_by != user_id or sandbox.status != "running" or not sandbox.access_url:
            await websocket.close(code=1008, reason="sandbox not available")
            return

        await websocket.accept()
        if is_vm(sandbox.runtime_id):
            await self.proxy_vnc(websocket, sandbox.runtime_id)
            return
        guest = hub.for_sandbox(sandbox_id)
        try:
            if guest is not None and guest.has("tunnel"):
                await self.proxy_tunnel(websocket, Tunnel(guest), sandbox)
                return
            if sandbox.access_url == TUNNEL_URL:
                raise ConnectionError("the sandbox's guest agent is not connected")
            async with websockets.connect(sandbox.access_url, max_size=None) as target:
                # log in to x11vnc here and offer the browser no-auth, so the password never leaves the API
                async def receive() -> bytes:
                    message = await target.recv()
                    return message if isinstance(message, bytes) else message.encode()

                upstream = Buffered(receive)
                await authenticate_async(upstream, target.send, vnc_password(sandbox))
                init = await offer_no_auth(websocket)
                if init:
                    await target.send(init)
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

    async def proxy_tunnel(self, websocket: WebSocket, tunnel: Tunnel, sandbox: Sandbox):
        """Bridges an accepted noVNC websocket to x11vnc through a guest tunnel, logging in as proxy() does."""
        await tunnel.open(VNC_PORT)
        try:

            async def receive() -> bytes:
                data = await tunnel.read()
                if not data:
                    raise ConnectionError("vnc server closed the connection")
                return data

            upstream = Buffered(receive)
            await authenticate_async(upstream, tunnel.write, vnc_password(sandbox))
            init = await offer_no_auth(websocket)
            if init:
                await tunnel.write(init)

            async def client_to_vnc():
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    await tunnel.write(message.get("bytes") or (message.get("text") or "").encode())

            async def vnc_to_client():
                if upstream.data:
                    await websocket.send_bytes(upstream.data)
                while data := await tunnel.read():
                    await websocket.send_bytes(data)

            tasks = [asyncio.create_task(client_to_vnc()), asyncio.create_task(vnc_to_client())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            await tunnel.close()

    async def terminal(self, websocket: WebSocket, sandbox_id: str, ticket: str = "", cols: int = 80, rows: int = 24):
        """A shell in the sandbox for a browser terminal. The client sends keystrokes as binary frames and
        {"type": "resize", "cols", "rows"} as text; it gets output as binary frames and {"type": "exit", "code"}."""
        user_id = tickets.redeem(ticket, f"terminal:{sandbox_id}")
        if user_id is None:
            await websocket.close(code=1008, reason="unauthorized")
            return
        with db_manager.session() as db:
            sandbox = db.get_sandbox(id=sandbox_id)
        guest = hub.for_sandbox(sandbox_id)
        if sandbox is None or sandbox.created_by != user_id or sandbox.status != "running":
            await websocket.close(code=1008, reason="sandbox not available")
            return
        if guest is None or not guest.has("pty"):
            await websocket.close(code=1011, reason="the sandbox's guest agent is not connected")
            return
        await websocket.accept()
        terminal = Terminal(guest)
        try:
            await terminal.open(max(1, min(cols, 1000)), max(1, min(rows, 1000)))
        except Exception as e:
            await websocket.close(code=1011, reason=str(e)[:120])
            return

        async def keystrokes():
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if message.get("bytes") is not None:
                    await terminal.write(message["bytes"])
                elif message.get("text"):
                    try:
                        control = json.loads(message["text"])
                        if control.get("type") == "resize":
                            await terminal.resize(
                                max(1, min(int(control["cols"]), 1000)), max(1, min(int(control["rows"]), 1000))
                            )
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue

        async def output():
            while True:
                kind, value = await terminal.events.get()
                if kind == "data":
                    await websocket.send_bytes(value)
                else:
                    await websocket.send_text(json.dumps({"type": "exit", "code": value}))
                    return

        tasks = [asyncio.create_task(keystrokes()), asyncio.create_task(output())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await terminal.close()
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close()

    async def proxy_vnc(self, websocket: WebSocket, runtime_id: str):
        """Bridges an accepted noVNC websocket to a macOS or Windows VM's VNC server over SSH. The proxy authenticates with the VM's
        password itself and offers the browser no-auth, so the password never leaves the API."""
        channel = None

        async def client_to_vm():
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                data = message.get("bytes") or (message.get("text") or "").encode()
                await asyncio.to_thread(channel.sendall, data)

        async def vm_to_client():
            while True:
                data = await asyncio.to_thread(channel.recv, 65536)
                if not data:
                    return
                await websocket.send_bytes(data)

        try:
            channel = await asyncio.to_thread(authenticated_channel, runtime_id)
            init = await offer_no_auth(websocket)
            if init:
                await asyncio.to_thread(channel.sendall, init)
            tasks = [asyncio.create_task(client_to_vm()), asyncio.create_task(vm_to_client())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        except Exception as e:
            self.logger.error("vnc proxy error", extra={"runtime_id": runtime_id, "error": repr(e)})
        finally:
            if channel is not None:
                channel.close()
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close()
