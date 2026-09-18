import asyncio
from fastapi import WebSocket, WebSocketDisconnect, HTTPException, Response
from server.proxy import forward_target_to_client, forward_client_to_target
import websockets
from server.sandbox import create_sandbox, delete_sandbox, get_sandbox
from server.tools import screenshot, click


class Handlers:
    @staticmethod
    def screenshotHandler(sandbox_id):
        sandbox = get_sandbox(sandbox_id=sandbox_id)
        if not sandbox:
            return {"message": "sandbox not found"}
        image = screenshot(sandbox["container_id"])
        return Response(
            content=image,
            media_type="image/png",
        )
    @staticmethod
    def clickHandler(sandbox_id, x, y, button):
        sandbox = get_sandbox(sandbox_id=sandbox_id)
        if not sandbox:
            return {"message": "sandbox not found"}
        result = click(sandbox["container_id"], x=x, y=y, button=button)
        return result
        

    @staticmethod
    def home():
        return {
            "message": "hello",
        }

    @staticmethod
    def create_sandbox():
        return create_sandbox()

    @staticmethod
    def get_sandbox(
        sandbox_id: str,
    ):
        sandbox = get_sandbox(sandbox_id)

        if not sandbox:
            raise HTTPException(
                status_code=404,
                detail="Sandbox not found",
            )

        return sandbox

    @staticmethod
    def delete_sandbox(
        sandbox_id: str,
    ):
        deleted = delete_sandbox(sandbox_id)

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="Sandbox not found",
            )

        return {
            "deleted": True,
            "id": sandbox_id,
        }

    @staticmethod
    async def proxy_websocket_endpoint(
        websocket: WebSocket,
        sandbox_id: str,
    ):
        sandbox = get_sandbox(sandbox_id)

        if not sandbox:
            await websocket.close(
                code=1008,
                reason="Sandbox not found",
            )
            return

        await websocket.accept()

        host_port = sandbox["host_port"]

        target_url = f"ws://127.0.0.1:{host_port}/websockify"

        print(f"Sandbox {sandbox_id}: connecting to {target_url}")

        try:
            async with websockets.connect(
                target_url,
                max_size=None,
            ) as target:
                print(f"Sandbox {sandbox_id}: VNC connected")

                client_to_target = asyncio.create_task(
                    forward_client_to_target(
                        websocket,
                        target,
                    )
                )

                target_to_client = asyncio.create_task(
                    forward_target_to_client(
                        target,
                        websocket,
                    )
                )

                done, pending = await asyncio.wait(
                    [
                        client_to_target,
                        target_to_client,
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()

                await asyncio.gather(
                    *pending,
                    return_exceptions=True,
                )

        except Exception as e:
            print(f"Sandbox {sandbox_id}: proxy error: {e!r}")

        finally:
            print(f"Sandbox {sandbox_id}: connection closed")
