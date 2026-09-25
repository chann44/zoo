import asyncio
import os
import uuid
from types import SimpleNamespace

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from db.connection import db_manager
from db.generated.models import Profile, Server, User
from db.generated.query import CreateProfileParams, CreateServerParams, Querier
from server.auth_api import AuthApi
from server.docker import connect, export_dir, remotes
from server.sandbox_api import PROFILE_APPS, PROFILE_DIR, SandboxApi


class ServerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    docker_url: str = Field(pattern=r"^(ssh|tcp)://.+")
    bind_address: str = Field(min_length=1, max_length=255)


class ServerResponse(BaseModel):
    id: str
    name: str
    docker_url: str
    bind_address: str
    created_at: str


class ServerStatus(BaseModel):
    online: bool
    error: str | None = None
    name: str | None = None
    os: str | None = None
    cpus: int | None = None
    memory_total: int | None = None
    docker_version: str | None = None
    containers_running: int | None = None
    sandboxes: int = 0


class ProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    app: str


class ProfileResponse(BaseModel):
    id: str
    name: str
    app: str
    size_bytes: int
    created_at: str


def server_response(server: Server) -> ServerResponse:
    return ServerResponse(**{k: getattr(server, k) for k in ServerResponse.model_fields})


def profile_response(profile: Profile) -> ProfileResponse:
    return ProfileResponse(**{k: getattr(profile, k) for k in ProfileResponse.model_fields})


def probe(server: Server) -> dict:
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
        "containers_running": info.get("ContainersRunning"),
    }


class ServersApi:
    def __init__(self, app: FastAPI, auth: AuthApi, sandboxes: SandboxApi):
        self.app = app
        self.auth = auth
        self.sandboxes = sandboxes
        os.makedirs(PROFILE_DIR, exist_ok=True)
        self._register_routes()

    def owned(self, server_id: str, user: User, db: Querier) -> Server:
        server = db.get_server(id=server_id)
        if server is None or server.created_by != user.id:
            raise HTTPException(status_code=404, detail="server not found")
        return server

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
            return [server_response(s) for s in db.list_servers_by_user(created_by=user.id)]

        @self.app.post("/servers", response_model=ServerResponse, status_code=201)
        async def add_server(payload: ServerRequest, user: User = Depends(current_user)) -> ServerResponse:
            server = SimpleNamespace(id=str(uuid.uuid4()), **payload.model_dump())
            status = await asyncio.to_thread(probe, server)
            if not status["online"]:
                raise HTTPException(status_code=400, detail=f"cannot reach docker: {status['error']}")
            with db_manager.session() as db:
                return server_response(db.create_server(
                        CreateServerParams(id=server.id, created_by=user.id, **payload.model_dump())
                    ))

        @self.app.get("/servers/{server_id}/status", response_model=ServerStatus)
        async def server_status(server_id: str, user: User = Depends(current_user)) -> ServerStatus:
            with db_manager.session() as db:
                server = self.owned(server_id, user, db)
                count = sum(1 for s in db.list_all_sandboxes() if s.server_id == server.id and s.status == "running")
            return ServerStatus(**await asyncio.to_thread(probe, server), sandboxes=count)

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
            try:
                data = await asyncio.to_thread(export_dir, sandbox.runtime_id, f"/home/zoo/{PROFILE_APPS[payload.app]}")
            except Exception:
                raise HTTPException(status_code=404, detail=f"no {payload.app} profile in this sandbox yet")
            profile_id = str(uuid.uuid4())
            with open(os.path.join(PROFILE_DIR, f"{profile_id}.tar"), "wb") as f:
                f.write(data)
            with db_manager.session() as db:
                return profile_response(
                    db.create_profile(
                        CreateProfileParams(
                            id=profile_id, user_id=user.id, name=payload.name, app=payload.app, size_bytes=len(data)
                        )
                    )
                )

        @self.app.post("/sandboxes/{sandbox_id}/profiles/{profile_id}", response_model=ProfileResponse)
        async def apply_profile(sandbox_id: str, profile_id: str, user: User = Depends(current_user)) -> ProfileResponse:
            with db_manager.session() as db:
                sandbox = self.sandboxes.running(sandbox_id, user, db)
                profile = self.profile(profile_id, user, db)
            await asyncio.to_thread(self.sandboxes.apply_profile, sandbox.runtime_id, profile)
            return profile_response(profile)

        @self.app.delete("/profiles/{profile_id}", status_code=204)
        def delete_profile(
            profile_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ):
            profile = self.profile(profile_id, user, db)
            db.delete_profile(id=profile.id)
            try:
                os.remove(os.path.join(PROFILE_DIR, f"{profile.id}.tar"))
            except FileNotFoundError:
                pass
