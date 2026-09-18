from fastapi import APIRouter, WebSocket
from server.handler import Handlers
from server.tools import screenshot

router = APIRouter(tags=["routes"])


@router.get("/", status_code=200)
def home():
    return Handlers.home()


@router.post("/sandboxes")
async def create_sandbox():
    return Handlers.create_sandbox()


@router.get("/sandboxes/{sandbox_id}")
async def get_sandbox(
    sandbox_id: str,
):
    return Handlers.get_sandbox(sandbox_id)


@router.delete("/sandboxes/{sandbox_id}")
async def delete_sandbox(
    sandbox_id: str,
):
    return Handlers.delete_sandbox(sandbox_id)


@router.post("/sandboxes/{sandbox_id}/screenshot")
async def capture_screenshot(sandbox_id: str):
    return Handlers.screenshotHandler(sandbox_id=sandbox_id)


@router.websocket("/sandboxes/{sandbox_id}/ws")
async def sandbox_websocket(
    websocket: WebSocket,
    sandbox_id: str,
):
    await Handlers.proxy_websocket_endpoint(
        websocket,
        sandbox_id,
    )
