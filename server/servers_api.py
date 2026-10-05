import asyncio
import logging
import os
import threading
import uuid
from types import SimpleNamespace
from typing import Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field

from db.connection import db_manager
from db.generated.models import Profile, Server, User
from db.generated.query import CreateProfileParams, CreateServerParams, Querier
from server import macos, tickets, windows
from server.auth_api import AuthApi
from server.docker import RUNTIME, connect, prepull, remotes, runtime_for
from server.platforms import PLATFORMS, capabilities_of, install_command, parse
from server.runtime import VMS, export_dir
from server.sandbox_api import PROFILE_APPS, PROFILE_DIR, SandboxApi, VncTicketResponse
from server.security import audit, encrypt_bytes, write_private
from server.ssh import trust

logger = logging.getLogger(__name__)


def prepull_images(servers: list[Server]) -> threading.Thread:
    """Pulls the Linux sandbox images onto every server that runs Linux sandboxes, in the background."""

    def run():
        for server in servers:
            if "linux" not in parse(server.capabilities):
                continue
            try:
                prepull(server)
            except Exception as e:
                logger.warning("image pre-pull failed", extra={"server_id": server.id, "error": str(e)})

    thread = threading.Thread(target=run, name="prepull", daemon=True)
    thread.start()
    return thread


class ServerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    docker_url: str = Field(pattern=r"^((ssh|tcp)://.+|local://)$")
    bind_address: str = Field(min_length=1, max_length=255)
    platform: Literal["linux", "macos", "windows"] = "linux"
    # the host's SSH key, from the node installer's join line; without it the API's known_hosts must have it
    host_key: str | None = Field(default=None, max_length=2000)


class ServerResponse(BaseModel):
    id: str
    name: str
    docker_url: str
    bind_address: str
    platform: str
    capabilities: list[str]
    created_at: str


class PlatformResponse(BaseModel):
    id: str
    name: str
    host: str
    kinds: list[str]
    runs: list[str]
    requirements: str
    servers: int  # this user's servers that can run it
    available: bool


class InstallCommand(BaseModel):
    platform: str
    command: str
    public_key: str
    requirements: str


class ServerStatus(BaseModel):
    online: bool
    error: str | None = None
    name: str | None = None
    os: str | None = None
    cpus: int | None = None
    memory_total: int | None = None
    docker_version: str | None = None
    microvm: bool | None = None
    containers_running: int | None = None
    sandboxes: int = 0


class BaseStatus(BaseModel):
    state: Literal["missing", "installing", "failed", "stopped", "running"]
    progress: float | None = None
    message: str | None = None
    ready: bool = False


class BaseInstallRequest(BaseModel):
    iso: str | None = Field(default=None, max_length=2000)
    edition: str | None = Field(default=None, max_length=100)


class ProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    app: str


class ProfileRename(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProfileResponse(BaseModel):
    id: str
    name: str
    app: str
    size_bytes: int
    created_at: str


def server_response(server: Server) -> ServerResponse:
    fields = {k: getattr(server, k) for k in ServerResponse.model_fields if k != "capabilities"}
    return ServerResponse(**fields, capabilities=sorted(parse(server.capabilities)))


def profile_response(profile: Profile) -> ProfileResponse:
    return ProfileResponse(**{k: getattr(profile, k) for k in ProfileResponse.model_fields})


def probe(server: Server) -> dict:
    if server.platform in VMS:
        return VMS[server.platform].probe(server.id, server.docker_url)
    try:
        info = connect(server.id, server.docker_url).info()
    except Exception as e:
        remotes.pop(server.id, None)
        return {"online": False, "error": str(e)[:500]}
    return {
        "online": True,
        "name": info.get("Name"),
        "os": info.get("OperatingSystem"),
        "cpus": info.get("NCPU"),
        "memory_total": info.get("MemTotal"),
        "docker_version": info.get("ServerVersion"),
        "microvm": RUNTIME in info.get("Runtimes", {}),
        "containers_running": info.get("ContainersRunning"),
    }


def has_docker(server) -> bool:
    """Whether a Mac or Windows host also has a Docker that can run Linux sandboxes, reached over the same SSH."""
    if server.docker_url == macos.LOCAL:
        return False  # the API's own Docker on this Mac already runs Linux sandboxes
    try:
        runtime_for(connect(server.id, server.docker_url))
    except Exception:
        remotes.pop(server.id, None)
        return False
    return True


def capabilities(server) -> str:
    return capabilities_of(server.platform, server.platform == "linux" or has_docker(server))


class ServersApi:
    def __init__(self, app: FastAPI, auth: AuthApi, sandboxes: SandboxApi):
        self.app = app
        self.auth = auth
        self.sandboxes = sandboxes
        os.makedirs(PROFILE_DIR, mode=0o700, exist_ok=True)
        os.chmod(PROFILE_DIR, 0o700)
        self._register_routes()

    def owned(self, server_id: str, user: User, db: Querier) -> Server:
        server = db.get_server(id=server_id)
        if server is None or server.created_by != user.id:
            raise HTTPException(status_code=404, detail="server not found")
        return server

    def vm_server(self, server_id: str, user: User):
        with db_manager.session() as db:
            server = self.owned(server_id, user, db)
        if server.platform not in VMS:
            raise HTTPException(status_code=400, detail="only macOS and Windows servers have a base VM")
        return server, VMS[server.platform]

    async def on_host(self, fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e)[:500])

    def all_sandboxes(self):
        with db_manager.session() as db:
            return list(db.list_all_sandboxes())

    def profile(self, profile_id: str, user: User, db: Querier) -> Profile:
        profile = db.get_profile(id=profile_id)
        if profile is None or profile.user_id != user.id:
            raise HTTPException(status_code=404, detail="profile not found")
        return profile

    def _register_routes(self):
        current_user = self.auth.current_user

        @self.app.get("/servers", response_model=list[ServerResponse])
        def list_servers(
            user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[ServerResponse]:
            macos.ensure_local_server(user.id, db)
            return [server_response(s) for s in db.list_servers_by_user(created_by=user.id)]

        @self.app.post("/servers", response_model=ServerResponse, status_code=201)
        async def add_server(payload: ServerRequest, user: User = Depends(current_user)) -> ServerResponse:
            if payload.platform == "macos" and not payload.docker_url.startswith(("ssh://", macos.LOCAL)):
                raise HTTPException(status_code=422, detail="macOS servers use ssh://user@host or local://")
            if payload.platform == "windows" and not payload.docker_url.startswith("ssh://"):
                raise HTTPException(status_code=422, detail="Windows servers use ssh://user@host")
            if payload.platform == "linux" and payload.docker_url == macos.LOCAL:
                raise HTTPException(
                    status_code=422, detail="local:// is only for macOS; this machine's Docker is built in"
                )
            if payload.host_key and payload.docker_url.startswith("ssh://"):
                target = urlparse(payload.docker_url)
                try:
                    trust(target.hostname or "", target.port or 22, payload.host_key)
                except ValueError as e:
                    raise HTTPException(status_code=422, detail=str(e))
            fields = payload.model_dump(exclude={"host_key"})
            server = SimpleNamespace(id=str(uuid.uuid4()), **fields)
            status = await asyncio.to_thread(probe, server)
            if not status["online"]:
                raise HTTPException(status_code=400, detail=f"cannot reach server: {status['error']}")
            if not status["microvm"]:
                if payload.platform == "windows":
                    raise HTTPException(status_code=400, detail="Hyper-V is not enabled on this server")
                raise HTTPException(
                    status_code=400, detail=f"docker runtime '{RUNTIME}' is not configured on this server"
                )
            caps = await asyncio.to_thread(capabilities, server)
            with db_manager.session() as db:
                created = db.create_server(
                    CreateServerParams(id=server.id, created_by=user.id, capabilities=caps, **fields)
                )
            if created is None:
                raise RuntimeError("server wasn't saved")
            prepull_images([created])
            return server_response(created)

        @self.app.get("/platforms", response_model=list[PlatformResponse])
        def list_platforms(
            user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[PlatformResponse]:
            """Every sandbox OS, and whether this install can run it. The control plane's own Docker runs Linux."""
            macos.ensure_local_server(user.id, db)
            servers = list(db.list_servers_by_user(created_by=user.id))
            result = []
            for p in PLATFORMS.values():
                count = sum(1 for s in servers if p.id in parse(s.capabilities))
                result.append(
                    PlatformResponse(
                        **{k: getattr(p, k) for k in ("id", "name", "host", "requirements")},
                        kinds=list(p.kinds),
                        runs=list(p.runs),
                        servers=count,
                        available=p.id == "linux" or count > 0,
                    )
                )
            return result

        @self.app.get("/servers/install-command", response_model=InstallCommand)
        def server_install_command(
            platform: Literal["linux", "macos", "windows"], request: Request, user: User = Depends(current_user)
        ) -> InstallCommand:
            try:
                key = macos.public_key()
            except RuntimeError as e:
                raise HTTPException(status_code=503, detail=f"{e}; set ZOO_SSH_DIR to a folder with an SSH key pair")
            api_url = os.environ.get("ZOO_API_URL") or str(request.base_url).rstrip("/")
            return InstallCommand(
                platform=platform,
                command=install_command(platform, key, api_url),
                public_key=key,
                requirements=PLATFORMS[platform].requirements,
            )

        @self.app.get("/servers/{server_id}/status", response_model=ServerStatus)
        async def server_status(server_id: str, user: User = Depends(current_user)) -> ServerStatus:
            with db_manager.session() as db:
                server = self.owned(server_id, user, db)
                count = sum(1 for s in db.list_all_sandboxes() if s.server_id == server.id and s.status == "running")
            status = await asyncio.to_thread(probe, server)
            if status["online"]:
                # Docker may have been installed or removed since the server was added
                caps = await asyncio.to_thread(capabilities, server)
                if caps != server.capabilities:
                    with db_manager.session() as db:
                        db.update_server_capabilities(capabilities=caps, id=server.id)
            return ServerStatus(**status, sandboxes=count)

        @self.app.get("/servers/{server_id}/base", response_model=BaseStatus)
        async def base_status(server_id: str, user: User = Depends(current_user)) -> BaseStatus:
            server, vms = self.vm_server(server_id, user)
            return BaseStatus(**await self.on_host(vms.base_status, server.id))

        @self.app.post("/servers/{server_id}/base/install", response_model=BaseStatus)
        async def base_install(
            server_id: str, payload: BaseInstallRequest | None = None, user: User = Depends(current_user)
        ) -> BaseStatus:
            server, vms = self.vm_server(server_id, user)
            status = await self.on_host(vms.base_status, server.id)
            if status["state"] not in ("missing", "failed"):
                raise HTTPException(status_code=409, detail=f"base VM is {status['state']}")
            if vms is windows:
                if payload is None or not payload.iso:
                    raise HTTPException(status_code=422, detail="give the path or URL of a Windows ISO on the server")
                await self.on_host(windows.base_install, server.id, payload.iso.strip(), payload.edition)
            else:
                await self.on_host(macos.base_install, server.id)
            return BaseStatus(state="installing", message="starting")

        @self.app.post("/servers/{server_id}/base/start", response_model=BaseStatus)
        async def base_start(server_id: str, user: User = Depends(current_user)) -> BaseStatus:
            server, vms = self.vm_server(server_id, user)
            status = await self.on_host(vms.base_status, server.id)
            if status["state"] != "stopped":
                raise HTTPException(status_code=409, detail=f"base VM is {status['state']}")
            # Windows sandboxes boot from frozen templates of the base, so only macOS needs them stopped.
            if vms is macos and any(
                s.server_id == server.id and s.status in ("running", "provisioning") for s in self.all_sandboxes()
            ):
                raise HTTPException(
                    status_code=409, detail="stop this server's macOS sandboxes before editing the base VM"
                )
            await self.on_host(vms.base_start, server.id)
            return BaseStatus(state="running")

        @self.app.post("/servers/{server_id}/base/stop", response_model=BaseStatus)
        async def base_stop(server_id: str, user: User = Depends(current_user)) -> BaseStatus:
            server, vms = self.vm_server(server_id, user)
            await self.on_host(vms.base_stop, server.id)
            return BaseStatus(state="stopped")

        @self.app.post("/servers/{server_id}/base/setup", status_code=204)
        async def base_setup(server_id: str, user: User = Depends(current_user)):
            server, vms = self.vm_server(server_id, user)
            if vms is not macos:
                raise HTTPException(status_code=400, detail="Windows base VMs set themselves up during install")
            await self.on_host(macos.base_setup, server.id)

        @self.app.post("/servers/{server_id}/base/vnc-ticket", response_model=VncTicketResponse)
        def base_vnc_ticket(server_id: str, user: User = Depends(current_user)) -> VncTicketResponse:
            server, _ = self.vm_server(server_id, user)
            return VncTicketResponse(ticket=tickets.issue(user.id, f"server:{server.id}"))

        @self.app.websocket("/servers/{server_id}/base/ws")
        async def base_screen(websocket: WebSocket, server_id: str, ticket: str = ""):
            user_id = tickets.redeem(ticket, f"server:{server_id}")
            with db_manager.session() as db:
                server = db.get_server(id=server_id)
            if user_id is None or server is None or server.created_by != user_id or server.platform not in VMS:
                await websocket.close(code=1008, reason="server not available")
                return
            await websocket.accept()
            await self.sandboxes.proxy_vnc(websocket, VMS[server.platform].base_id(server.id))

        @self.app.delete("/servers/{server_id}", status_code=204)
        def delete_server(
            server_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ):
            server = self.owned(server_id, user, db)
            if any(s.server_id == server.id for s in db.list_all_sandboxes()):
                raise HTTPException(status_code=409, detail="move or delete the sandboxes on this server first")
            db.detach_server(server_id=server.id)
            db.delete_server(id=server.id)
            remotes.pop(server.id, None)
            macos.forget(server.id)
            windows.forget(server.id)

        @self.app.get("/profiles", response_model=list[ProfileResponse])
        def list_profiles(
            user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[ProfileResponse]:
            return [profile_response(p) for p in db.list_profiles_by_user(user_id=user.id)]

        @self.app.get("/profile-apps")
        def profile_apps(user: User = Depends(current_user)) -> dict[str, str]:
            return PROFILE_APPS

        @self.app.post("/sandboxes/{sandbox_id}/profiles", response_model=ProfileResponse, status_code=201)
        async def capture_profile(
            sandbox_id: str, payload: ProfileRequest, user: User = Depends(current_user)
        ) -> ProfileResponse:
            if payload.app not in PROFILE_APPS:
                raise HTTPException(status_code=422, detail=f"app must be one of {', '.join(PROFILE_APPS)}")
            with db_manager.session() as db:
                sandbox = self.sandboxes.running(sandbox_id, user, db)
            if sandbox.kind in VMS:
                raise HTTPException(
                    status_code=400, detail="app profiles aren't supported on macOS and Windows sandboxes yet"
                )
            try:
                data = await asyncio.to_thread(export_dir, sandbox.runtime_id, f"/home/zoo/{PROFILE_APPS[payload.app]}")
            except Exception:
                raise HTTPException(status_code=404, detail=f"no {payload.app} profile in this sandbox yet")
            profile_id = str(uuid.uuid4())
            token = await asyncio.to_thread(encrypt_bytes, data)
            write_private(os.path.join(PROFILE_DIR, f"{profile_id}.tar"), token)
            with db_manager.session() as db:
                profile = db.create_profile(
                    CreateProfileParams(
                        id=profile_id,
                        user_id=user.id,
                        name=payload.name,
                        app=payload.app,
                        size_bytes=len(data),
                        encrypted=1,
                    )
                )
                audit(
                    db, user, "profile.capture", "profile", profile.id, sandbox.id, name=profile.name, app=profile.app
                )
                return profile_response(profile)

        @self.app.post("/sandboxes/{sandbox_id}/profiles/{profile_id}", response_model=ProfileResponse)
        async def apply_profile(
            sandbox_id: str, profile_id: str, user: User = Depends(current_user)
        ) -> ProfileResponse:
            with db_manager.session() as db:
                sandbox = self.sandboxes.running(sandbox_id, user, db)
                profile = self.profile(profile_id, user, db)
            if sandbox.kind in VMS:
                raise HTTPException(
                    status_code=400, detail="app profiles aren't supported on macOS and Windows sandboxes yet"
                )
            await asyncio.to_thread(self.sandboxes.apply_profile, sandbox.runtime_id, profile)
            with db_manager.session() as db:
                audit(db, user, "profile.load", "profile", profile.id, sandbox.id, name=profile.name, app=profile.app)
            return profile_response(profile)

        @self.app.patch("/profiles/{profile_id}", response_model=ProfileResponse)
        def rename_profile(
            profile_id: str,
            payload: ProfileRename,
            user: User = Depends(current_user),
            db: Querier = Depends(db_manager.get_client),
        ) -> ProfileResponse:
            profile = self.profile(profile_id, user, db)
            renamed = db.rename_profile(name=payload.name.strip(), id=profile.id)
            audit(db, user, "profile.rename", "profile", profile.id, name=renamed.name, previous=profile.name)
            return profile_response(renamed)

        @self.app.delete("/profiles/{profile_id}", status_code=204)
        def delete_profile(
            profile_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ):
            profile = self.profile(profile_id, user, db)
            db.delete_profile(id=profile.id)
            audit(db, user, "profile.delete", "profile", profile.id, name=profile.name, app=profile.app)
            try:
                os.remove(os.path.join(PROFILE_DIR, f"{profile.id}.tar"))
            except FileNotFoundError:
                pass
