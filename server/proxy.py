import websockets
from fastapi import WebSocket, WebSocketDisconnect


async def forward_client_to_target(client: WebSocket, target):
    try:
        while True:
            message = await client.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await target.send(message["bytes"])
            elif message.get("text") is not None:
                await target.send(message["text"])
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        pass


async def forward_target_to_client(target, client: WebSocket):
    try:
        async for message in target:
            if isinstance(message, bytes):
                await client.send_bytes(message)
            else:
                await client.send_text(message)
    except websockets.exceptions.ConnectionClosed:
        pass
