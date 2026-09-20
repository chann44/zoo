from contextlib import asynccontextmanager


from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from mcp_tools.server import mcp


from server.router import router


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
            ],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self.app.include_router(router)
        self.app.mount("/mcp", mcp_app)

    def start(self, import_string: str = "main:app"):
        uvicorn.run(import_string, host="127.0.0.1", port=self.port, reload=True)
