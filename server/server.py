import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from mcp_tools.server import build_mcp
from server.router import router
from server.auth_api import AuthApi
from server.admin_api import AdminApi
from server.servers_api import ServersApi
from server.sandbox_api import SandboxApi
from server.policy_api import SandboxPolicyApi
from server.monitor import MonitoringApi
from server.telemetry import setup_telemetry
from db.connection import db_manager


class Server:
    def __init__(self, port=8000):
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            watcher = asyncio.create_task(self.sandbox_api.watch())
            async with self.mcp.session_manager.run():
                yield
            watcher.cancel()

        self.app = FastAPI(lifespan=lifespan)
        setup_telemetry(self.app)
        self.port = port

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(","),
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        db_manager.init_db(os.environ.get("DB_PATH", "./local.db"))

        self.app.include_router(router)
        self.auth_api = AuthApi(self.app)
        self.sandbox_api = SandboxApi(self.app, self.auth_api)
        self.policy_api = SandboxPolicyApi(self.app, self.auth_api, self.sandbox_api)
        self.monitoring_api = MonitoringApi(self.app, self.auth_api)
        self.admin_api = AdminApi(self.app, self.auth_api)
        self.servers_api = ServersApi(self.app, self.auth_api, self.sandbox_api)
        self.mcp = build_mcp(self.auth_api, self.sandbox_api)
        self.app.mount("/mcp", self.mcp.streamable_http_app(streamable_http_path="/"))

    def start(self, import_string: str = "main:app"):
        uvicorn.run(
            import_string,
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", self.port)),
            reload=os.environ.get("RELOAD", "1") == "1",
        )
