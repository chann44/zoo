import websockets
from fastapi import WebSocket, WebSocketDisconnect


async def forward_client_to_target(
    client: WebSocket,
    target,
):
    print("CLIENT -> TARGET STARTED")

    try:
        while True:
            message = await client.receive()

            print("CLIENT MESSAGE:", message["type"])

            if message["type"] == "websocket.disconnect":
                print("CLIENT DISCONNECTED")
                break

            if message.get("bytes") is not None:
                data = message["bytes"]

                print(
                    f"CLIENT -> TARGET: {len(data)} bytes"
                )

                await target.send(data)

            elif message.get("text") is not None:
                data = message["text"]

                print(
                    f"CLIENT -> TARGET: {len(data)} text"
                )

                await target.send(data)

    except WebSocketDisconnect:
        print("CLIENT WEBSOCKET DISCONNECTED")

    except websockets.exceptions.ConnectionClosed as e:
        print("TARGET CONNECTION CLOSED:", e)

    except Exception as e:
        print("CLIENT -> TARGET ERROR:", repr(e))


async def forward_target_to_client(
    target,
    client: WebSocket,
):
    print("TARGET -> CLIENT STARTED")

    try:
        async for message in target:

            print(
                "TARGET MESSAGE:",
                type(message),
                len(message),
            )

            if isinstance(message, bytes):
                await client.send_bytes(message)

            elif isinstance(message, str):
                await client.send_text(message)

    except websockets.exceptions.ConnectionClosed as e:
        print("TARGET WEBSOCKET CLOSED:", e)

    except Exception as e:
        print("TARGET -> CLIENT ERROR:", repr(e))