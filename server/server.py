from fastapi import FastAPI, HTTPException
import uvicorn

from server.router import router


class Server:
    def __init__(self, port=8000):
        self.app = FastAPI()
        self.port = port
        self.app.include_router(router)
    
    def start(self, import_string: str = "main:app"):
        
        uvicorn.run(import_string, host="127.0.0.1", port=self.port, reload=True)
        
         

   
