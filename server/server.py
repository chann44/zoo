from fastapi import FastAPI, HTTPException
import uvicorn


class Server:
    def __init__(self, port=8000):
        self.app = FastAPI()
        self.port = port
    
    def start(self, import_string: str = "main:app"):
        app = FastAPI()
        uvicorn.run(import_string, host="127.0.0.1", port=self.port, reload=True)
        
         

   
