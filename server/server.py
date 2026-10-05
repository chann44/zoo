import asyncio
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.connection import db_manager
from integrations import discord, slack, whatsapp
from mcp_tools.server import build_mcp
from server import health
from server.admin_api import AdminApi
from server.agent_api import AgentApi
from server.auth_api import AuthApi
from server.monitor import MonitoringApi
from server.policy_api import SandboxPolicyApi
from server.router import router
from server.sandbox_api import SandboxApi
from server.security import require_secrets_key
from server.servers_api import ServersApi
from server.telemetry import setup_telemetry
from server.vault_api import VaultApi


class Server:
    def __init__(self, port=8000):
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            with db_manager.session() as db:
                require_secrets_key(db)
            jobs = asyncio.create_task(self.sandbox_api.jobs.run())
            watcher = asyncio.create_task(self.sandbox_api.watch())
            bot = asyncio.create_task(discord.run(self.agent_api)) if discord.configured() else None
            async with self.mcp.session_manager.run():
                yield
            # drain: unfinished jobs are requeued and resume on the next start
            watcher.cancel()
            if bot is not None:
                bot.cancel()
            await asyncio.gather(self.sandbox_api.jobs.shutdown(), self.agent_api.shutdown())
            jobs.cancel()

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
        health.register(self.app)
        self.auth_api = AuthApi(self.app)
        self.sandbox_api = SandboxApi(self.app, self.auth_api)
        self.agent_api = AgentApi(self.app, self.auth_api, self.sandbox_api)
        slack.register(self.app, self.agent_api)
        whatsapp.register(self.app, self.agent_api)
        self.policy_api = SandboxPolicyApi(self.app, self.auth_api, self.sandbox_api)
        self.monitoring_api = MonitoringApi(self.app, self.auth_api)
        self.admin_api = AdminApi(self.app, self.auth_api)
        self.servers_api = ServersApi(self.app, self.auth_api, self.sandbox_api)
        self.vault_api = VaultApi(self.app, self.auth_api, self.sandbox_api)
        self.mcp = build_mcp(self.auth_api, self.sandbox_api)
        self.app.mount("/mcp", self.mcp.streamable_http_app(streamable_http_path="/"))

    def start(self, import_string: str = "main:app"):
        uvicorn.run(
            import_string,
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", self.port)),
            reload=os.environ.get("RELOAD", "1") == "1",
            # long-lived connections (desktop viewers, agent streams) get this long to close before shutdown
            timeout_graceful_shutdown=15,
        )
