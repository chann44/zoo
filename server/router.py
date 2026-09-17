from fastapi import APIRouter, WebSocket
from server.handler import Handlers

router = APIRouter(tags=["routes"]) 

@router.websocket("/ws")
def socket(websocket: WebSocket):
    return Handlers.proxy_websocket_endpoint(websocket=websocket)

@router.get("/", status_code=200)
def home():
    return Handlers.home() 


