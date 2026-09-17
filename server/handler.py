import asyncio
from fastapi import  WebSocket, WebSocketDisconnect
from server.proxy import forward_target_to_client, forward_client_to_target 
import websockets


TARGET_WS_URL = "ws://localhost:6080/websockify"

class Handlers:
    
    @staticmethod
    def home():
        return {
            "message": "hello",
        }
    @staticmethod
    async def proxy_websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        print("Client connected to FastAPI proxy. Opening connection to backend target...")
    
        try:
            async with websockets.connect(TARGET_WS_URL) as target_ws:
                print("Connected to noVNC/websockify")
                client_to_target = forward_client_to_target(websocket, target_ws)
                target_to_client = forward_target_to_client(target_ws, websocket)
            
                await asyncio.gather(client_to_target, target_to_client)
            
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            print("Connections closed.")