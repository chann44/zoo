from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from server.router import router


class Server:
    def __init__(self, port=8000):
        self.app = FastAPI()
        self.port = port

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],     
            allow_credentials=False, 
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self.app.include_router(router)

    def start(self, import_string: str = "main:app"):
        uvicorn.run(import_string, host="127.0.0.1", port=self.port, reload=True)