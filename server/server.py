from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from mcp import server as mcp


from server.router import router


class Server:
    def __init__(self, port=8000):
        self.app = FastAPI()
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
        self.app.mount("/mcp", mcp.streamable_http_app())

    def start(self, import_string: str = "main:app"):
        uvicorn.run(import_string, host="127.0.0.1", port=self.port, reload=True)
