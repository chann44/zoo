"""The connection gateway, for a Zoo running as several API and worker processes (the Helm chart).

zoo-guest websockets and zoo-node streams are long-lived, and each one lands on a single process, while any API or
worker process may need it. With ZOO_ROLE=gateway one process holds them all: guests dial its /guest/connect and
nodes its gRPC port (ZOO_NODE_PORT). Every other process sets ZOO_GATEWAY to the gateway's internal URL and reaches
guests and nodes through it (server/guest.py RemoteHub, server/nodes.py RemoteNodeHub):

  GET  /internal/guests/{sandbox_id}         whether the sandbox's guest is connected, and its status
  WS   /internal/guests/{sandbox_id}/relay   the guest protocol to that guest, with request ids and streams of its own
  GET  /internal/nodes/{server_id}           whether the server's node is connected, and what it reaches
  WS   /internal/nodes/{server_id}/tunnel    a byte stream to the node's `docker` or `ssh` target
  POST /internal/nodes/{server_id}/drop      ends the node's stream

The gateway holds no state of its own: when it restarts, guests and nodes dial it again within seconds. Requests
carry a token derived from the secrets key, which every process of one install shares."""

import asyncio
import contextlib
import hashlib
import hmac
import logging
import os
import socket
import time

import httpx
from fastapi import FastAPI, Header, WebSocket
from fastapi.responses import JSONResponse

URL = os.environ.get("ZOO_GATEWAY", "").rstrip("/")
TIMEOUT = 5
# how often a relay passes the guest's metrics and liveness on
METRICS_SECONDS = 5

logger = logging.getLogger(__name__)


def enabled() -> bool:
    """Whether this process reaches guests and nodes through a gateway."""
    return bool(URL)


def token() -> str:
    key = (os.environ.get("ZOO_SECRETS_KEY") or os.environ["JWT_SECRET"]).encode()
    return hmac.new(key, b"zoo-gateway", hashlib.sha256).hexdigest()


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {token()}"}


def authorized(given: str) -> bool:
    return hmac.compare_digest(given.encode(), f"Bearer {token()}".encode())


def ws_url(path: str) -> str:
    return ("ws" + URL[4:] if URL.startswith("http") else URL) + path


def get(path: str) -> dict:
    response = httpx.get(URL + path, headers=headers(), timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def post(path: str):
    httpx.post(URL + path, headers=headers(), timeout=TIMEOUT).raise_for_status()


class Cached:
    """Answers from the gateway, kept for a moment: tools ask about a sandbox's guest on every call."""

    def __init__(self, ttl: float = 1.0):
        self.ttl = ttl
        self.answers: dict[str, tuple[float, dict]] = {}

    def __call__(self, path: str, fresh: bool = False) -> dict:
        now = time.monotonic()
        found = self.answers.get(path)
        if found is not None and not fresh and now - found[0] < self.ttl:
            return found[1]
        try:
            answer = get(path)
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("gateway unreachable", extra={"path": path, "error": str(e)})
            answer = {}
        self.answers[path] = (now, answer)
        return answer


# --- the gateway's side ---


def register(app: FastAPI):
    from server import nodes
    from server.guest import STREAM_ENDS, GuestError, hub, pack, unpack

    def refuse(given: str) -> JSONResponse | None:
        return None if authorized(given) else JSONResponse({"detail": "unauthorized"}, status_code=401)

    @app.get("/internal/guests/{sandbox_id}", include_in_schema=False)
    def guest_status(sandbox_id: str, authorization: str = Header("")):
        return refuse(authorization) or {**hub.status(sandbox_id), "heartbeat": hub.heartbeat(sandbox_id)}

    @app.get("/internal/nodes/{server_id}", include_in_schema=False)
    def node_status(server_id: str, authorization: str = Header("")):
        return refuse(authorization) or {
            "connected": nodes.hub.connected(server_id),
            "targets": sorted(nodes.hub.targets(server_id)),
        }

    @app.post("/internal/nodes/{server_id}/drop", include_in_schema=False)
    def drop_node(server_id: str, authorization: str = Header("")):
        if (refused := refuse(authorization)) is not None:
            return refused
        nodes.hub.drop(server_id)
        return {"ok": True}

    @app.websocket("/internal/guests/{sandbox_id}/relay")
    async def relay(websocket: WebSocket, sandbox_id: str):
        guest = hub.guests.get(sandbox_id)
        if not authorized(websocket.headers.get("authorization", "")) or guest is None:
            await websocket.close(code=1008, reason="unauthorized or no guest")
            return
        await websocket.accept()
        loop = asyncio.get_running_loop()
        outbox: asyncio.Queue[bytes | None] = asyncio.Queue()
        # this relay's open streams: id -> what closes it on the guest
        streams: dict[str, str] = {}

        def send(header: dict, payload: bytes = b""):
            loop.call_soon_threadsafe(outbox.put_nowait, pack(header, payload))

        def stream_frame(header: dict, payload: bytes):
            if header.get("op") in STREAM_ENDS:
                streams.pop(header.get("stream", ""), None)
            send(header, payload)

        def liveness() -> dict:
            return {"metrics": guest.metrics, "quiet": time.monotonic() - guest.seen}

        async def answer(header: dict, payload: bytes):
            op, args = header.get("op", ""), header.get("args") or {}
            stream = args.get("stream") if op in ("pty_open", "tunnel_open") else None
            if stream:
                # registered before asking, since the stream can speak ahead of the reply
                streams[stream] = "pty_kill" if op == "pty_open" else "tunnel_close"
                guest.streams[stream] = stream_frame
            try:
                result, data = await guest.request(op, args, payload, float(header.get("timeout", 600)))
                send({"id": header["id"], "ok": True, "result": result}, data)
            except (GuestError, TimeoutError) as e:
                if stream:
                    streams.pop(stream, None)
                    guest.streams.pop(stream, None)
                send({"id": header["id"], "ok": False, "error": str(e) or "guest timed out"})

        async def sender():
            while (frame := await outbox.get()) is not None:
                await websocket.send_bytes(frame)

        async def watch():
            while hub.guests.get(sandbox_id) is guest:
                await asyncio.sleep(METRICS_SECONDS)
                send({"op": "metrics", **liveness()})
            await websocket.close(code=1011, reason="guest disconnected")

        await websocket.send_bytes(
            pack(
                {
                    "op": "hello",
                    "version": guest.version,
                    "os": guest.os,
                    "services": sorted(guest.services),
                    **liveness(),
                }
            )
        )
        tasks = {asyncio.create_task(sender()), asyncio.create_task(watch())}
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                frame = message.get("bytes")
                if not frame:
                    continue
                header, payload = unpack(frame)
                if "id" in header:
                    task = asyncio.create_task(answer(header, payload))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                    continue
                if header.get("op") in ("pty_kill", "tunnel_close"):
                    stream = (header.get("args") or {}).get("stream", "")
                    streams.pop(stream, None)
                    guest.streams.pop(stream, None)
                await guest.websocket.send_bytes(frame)
        except Exception:
            logger.debug("guest relay ended", extra={"sandbox_id": sandbox_id}, exc_info=True)
        finally:
            for stream, close in list(streams.items()):
                guest.streams.pop(stream, None)
                with contextlib.suppress(Exception):
                    await guest.websocket.send_bytes(pack({"op": close, "args": {"stream": stream}}))
            outbox.put_nowait(None)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    @app.websocket("/internal/nodes/{server_id}/tunnel")
    async def tunnel(websocket: WebSocket, server_id: str, target: str = ""):
        if not authorized(websocket.headers.get("authorization", "")):
            await websocket.close(code=1008, reason="unauthorized")
            return
        try:
            sock = await asyncio.to_thread(nodes.hub.open, server_id, target)
        except nodes.Closed as e:
            await websocket.close(code=1011, reason=str(e)[:120])
            return
        await websocket.accept()
        sock.setblocking(False)
        loop = asyncio.get_running_loop()

        async def up():
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if data := message.get("bytes"):
                    await loop.sock_sendall(sock, data)

        async def down():
            while data := await loop.sock_recv(sock, nodes.CHUNK):
                await websocket.send_bytes(data)

        tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            sock.close()
            with contextlib.suppress(Exception):
                await websocket.close()
