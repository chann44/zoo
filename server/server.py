import os
from contextlib import asynccontextmanager


from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from mcp_tools.server import mcp


from server.router import router
from server.auth_api import AuthApi
from server.sandbox_api import SandboxApi
from server.policy_api import SandboxPolicyApi
from server.monitor import MonitoringApi
from db.connection import db_manager


class Server:
    def __init__(self, port=8000):
        mcp_app = mcp.streamable_http_app(streamable_http_path="/")

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            async with mcp.session_manager.run():
                yield

        self.app = FastAPI(lifespan=lifespan)
        self.port = port

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",
                "http://localhost:3000",
            ],
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
        self.app.mount("/mcp", mcp_app)

    def start(self, import_string: str = "main:app"):
        uvicorn.run(import_string, host="127.0.0.1", port=self.port, reload=True)
