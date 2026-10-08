import asyncio
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.connection import db_manager
from integrations import discord, relay, slack, whatsapp
from logger.logger import logger
from mcp_tools.server import build_mcp
from server import health, nodes, workers
from server.admin_api import AdminApi
from server.agent_api import AgentApi
from server.auth_api import AuthApi
from server.monitor import MonitoringApi
from server.nodes_api import NodesApi
from server.policy_api import SandboxPolicyApi
from server.router import router
from server.sandbox_api import SandboxApi
from server.security import require_secrets_key
from server.servers_api import ServersApi, prepull_images
from server.telemetry import setup_telemetry
from server.vault_api import VaultApi, remind


async def housekeeping():
    """Hourly upkeep: forgets old chat events and logs vault secrets that are due for rotation or expiring."""
    while True:
        try:
            await asyncio.to_thread(relay.purge_events)
            await asyncio.to_thread(remind)
        except Exception as e:
            logger.error("housekeeping failed", extra={"error": repr(e)})
        await asyncio.sleep(3600)


class Server:
    def __init__(self, port=8000):
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            with db_manager.session() as db:
                require_secrets_key(db)
                if workers.works():
                    prepull_images(list(db.list_all_servers()))
            # every process holds its own node streams, since each reaches hosts through them
            node_server = None
            if os.environ.get("ZOO_NODE_PORT") != "off":
                node_server, _ = await asyncio.to_thread(nodes.serve)
            background: list[asyncio.Task] = []
            if workers.works():
                background = [
                    asyncio.create_task(self.sandbox_api.watch()),
                    asyncio.create_task(self.sandbox_api.pool.run()),
                    asyncio.create_task(self.agent_api.work()),
                    asyncio.create_task(housekeeping()),
                ]
                if discord.configured():
                    background.append(asyncio.create_task(discord.supervise(self.agent_api)))
                jobs = asyncio.create_task(self.sandbox_api.jobs.run())
            else:
                jobs = None
            async with self.mcp.session_manager.run():
                yield
            # drain: unfinished jobs are requeued and agent runs handed back; both resume on the next start
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            await asyncio.gather(self.sandbox_api.jobs.shutdown(), self.agent_api.shutdown())
            if jobs is not None:
                jobs.cancel()
            if node_server is not None:
                await asyncio.to_thread(nodes.stop, node_server)

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
        self.nodes_api = NodesApi(self.app, self.auth_api)
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
