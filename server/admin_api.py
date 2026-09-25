import asyncio
import os
import socket
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field

from server.auth_api import AuthApi, UserResponse
from server.sandbox_api import SandboxResponse, to_response
from db.generated.query import Querier
from db.generated.models import User
from db.connection import db_manager

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "./backups"))
PUBLIC_IP = os.environ.get("ZOO_PUBLIC_IP")


class DomainRequest(BaseModel):
    hostname: str = Field(max_length=253, pattern=r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class DomainResponse(BaseModel):
    id: str
    hostname: str
    url: str
    addresses: list[str]
    public_ip: str | None
    points_here: bool | None
    created_at: str


def resolve(hostname: str) -> list[str]:
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(hostname, None, socket.AF_INET)})
    except socket.gaierror:
        return []


class BackupResponse(BaseModel):
    name: str
    size: int
    created_at: str


class AdminApi:
    def __init__(self, app: FastAPI, auth: AuthApi):
        self.app = app
        self.auth = auth
        self.admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
        self._register_routes()

    def _register_routes(self):
        current_user = self.auth.current_user

        def admin_user(user: User = Depends(current_user)) -> User:
            if user.email.lower() not in self.admins:
                raise HTTPException(status_code=403, detail="admin only")
            return user

        @self.app.get("/admin/users", response_model=list[UserResponse])
        def list_users(
            _: User = Depends(admin_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[UserResponse]:
            return [UserResponse(id=u.id, email=u.email, name=u.name, avatar_url=u.avatar_url) for u in db.list_users()]

        @self.app.get("/admin/sandboxes", response_model=list[SandboxResponse])
        def list_sandboxes(
            _: User = Depends(admin_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[SandboxResponse]:
            return [to_response(s) for s in db.list_all_sandboxes()]

        @self.app.get("/admin/domains", response_model=list[DomainResponse])
        async def list_domains(_: User = Depends(admin_user)) -> list[DomainResponse]:
            with db_manager.session() as db:
                domains = list(db.list_domains())
            return list(await asyncio.gather(*(asyncio.to_thread(self._domain, d) for d in domains)))

        @self.app.post("/admin/domains", response_model=DomainResponse, status_code=201)
        def add_domain(
            payload: DomainRequest, user: User = Depends(admin_user), db: Querier = Depends(db_manager.get_client)
        ) -> DomainResponse:
            if db.get_domain_by_hostname(hostname=payload.hostname) is not None:
                raise HTTPException(status_code=409, detail="domain already added")
            return self._domain(db.create_domain(id=str(uuid.uuid4()), hostname=payload.hostname, created_by=user.id))

        @self.app.delete("/admin/domains/{domain_id}", status_code=204)
        def delete_domain(
            domain_id: str, _: User = Depends(admin_user), db: Querier = Depends(db_manager.get_client)
        ):
            db.delete_domain(id=domain_id)

        @self.app.get("/domains/check")
        def check_domain(domain: str, db: Querier = Depends(db_manager.get_client)):
            if domain != os.environ.get("ZOO_DOMAIN") and db.get_domain_by_hostname(hostname=domain.lower()) is None:
                raise HTTPException(status_code=404, detail="unknown domain")
            return {"ok": True}

        @self.app.post("/admin/backups", response_model=BackupResponse, status_code=201)
        def create_backup(_: User = Depends(admin_user)) -> BackupResponse:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            target = BACKUP_DIR / f"zoo-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.db"
            source = sqlite3.connect(db_manager._db_path)
            dest = sqlite3.connect(target)
            with dest:
                source.backup(dest)
            source.close()
            dest.close()
            return self._backup(target)

        @self.app.get("/admin/backups", response_model=list[BackupResponse])
        def list_backups(_: User = Depends(admin_user)) -> list[BackupResponse]:
            return [self._backup(p) for p in sorted(BACKUP_DIR.glob("zoo-*.db"), reverse=True)]

    def _domain(self, domain) -> DomainResponse:
        addresses = resolve(domain.hostname)
        return DomainResponse(
            id=domain.id,
            hostname=domain.hostname,
            url=f"https://{domain.hostname}",
            addresses=addresses,
            public_ip=PUBLIC_IP,
            points_here=PUBLIC_IP in addresses if PUBLIC_IP else None,
            created_at=domain.created_at,
        )

    def _backup(self, path: Path) -> BackupResponse:
        stat = path.stat()
        return BackupResponse(
            name=path.name,
            size=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        )
