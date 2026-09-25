import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel

from server.auth_api import AuthApi, UserResponse
from server.sandbox_api import SandboxResponse, to_response
from db.generated.query import Querier
from db.generated.models import User
from db.connection import db_manager

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "./backups"))


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

    def _backup(self, path: Path) -> BackupResponse:
        stat = path.stat()
        return BackupResponse(
            name=path.name,
            size=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        )
