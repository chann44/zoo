"""Shared plumbing for chat platforms: route an incoming message to the linked sandbox's agent and stream the
run back as the platform allows (one message edited in place, or a message per step).

Platform events are recorded in the database the first time they're seen, so a platform's retries and duplicate
deliveries start nothing twice, on any replica and across restarts. Only users on a channel's allowlist can command
its sandbox. Calls out to a platform's API retry with backoff on rate limits, server errors and dropped connections.
"""

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

import httpx
from fastapi import HTTPException

from db.connection import db_manager
from logger.logger import logger
from server import metrics
from server.jobs import stamp

HELP = "Send a task and I'll do it on the sandbox desktop. `stop` cancels the current task, `reset` clears the conversation."
EDIT_INTERVAL = 1.2
# events are remembered this long; platforms stop retrying well within it
EVENT_TTL = 24 * 3600
ATTEMPTS = 4
MAX_DELAY = 30.0
# httpx transport for outgoing platform calls; tests swap in an httpx.MockTransport
transport: httpx.AsyncBaseTransport | None = None
tasks: set[asyncio.Task] = set()


class Retryable(Exception):
    """A platform call that may succeed if made again, after `after` seconds when the platform said so."""

    def __init__(self, message: str, after: float | None = None):
        super().__init__(message)
        self.after = after


def retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None


async def retry[T](call: Callable[[], Awaitable[T]], attempts: int = ATTEMPTS, base: float = 1.0) -> T:
    """Makes a platform call, retrying with exponential backoff and jitter on Retryable errors and network errors."""
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except (Retryable, httpx.TransportError) as e:
            if attempt == attempts:
                metrics.error("chat")
                raise
            after = e.after if isinstance(e, Retryable) and e.after is not None else base * 2 ** (attempt - 1)
            delay = min(after, MAX_DELAY) + random.uniform(0, base / 4)
            logger.warning("chat platform call failed, retrying", extra={"error": str(e), "delay": round(delay, 2)})
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15, transport=transport)


def first_time(platform: str, event_id: str) -> bool:
    """Records a platform event; False when it was already handled (a retry or a duplicate delivery)."""
    if not event_id:
        return True
    with db_manager.session() as db:
        return db.record_chat_event(platform=platform, event_id=event_id) is not None


def purge_events():
    with db_manager.session() as db:
        db.purge_chat_events(created_at=stamp(-EVENT_TTL))


def spawn(coroutine: Coroutine[Any, Any, None]):
    """Runs a message's handling in the background, so the webhook answers the platform right away."""
    task = asyncio.create_task(coroutine)
    tasks.add(task)
    task.add_done_callback(tasks.discard)


def render(events: list[dict], limit: int) -> str:
    lines = []
    for e in events:
        if e["type"] == "text":
            lines.append(e["text"])
        elif e["type"] == "action":
            lines.append(f"› {e['text']}")
        elif e["type"] == "status":
            lines.append(f"ℹ️ {e['text']}")
        elif e["type"] == "error":
            lines.append(f"⚠️ {e['text']}")
    text = "\n".join(lines).strip()
    return text if len(text) <= limit else "…" + text[-(limit - 1) :]


def resolve(platform: str, external_id: str):
    """Returns (sandbox_id, user, allowed user IDs) for a linked channel, or None."""
    with db_manager.session() as db:
        channel = db.get_agent_channel(platform=platform, external_id=external_id)
        if channel is None:
            return None
        return channel.sandbox_id, db.get_user(id=channel.created_by), json.loads(channel.allowed_users or "[]")


def permitted(platform: str, external_id: str, author: str, allowed: list[str]) -> bool:
    if platform == "whatsapp":
        # a WhatsApp link is the sender's own number
        return author == external_id
    return "*" in allowed or author in allowed


async def handle(
    agent,
    platform: str,
    external_id: str,
    author: str,
    text: str,
    send: Callable[[str], Awaitable[Any]],
    edit: Callable[[Any, str], Awaitable[None]] | None,
    limit: int,
):
    """Runs one incoming chat message. With `edit`, the reply is a single message updated as the agent works;
    without it, each assistant message and the actions before it go out as new messages."""
    linked = resolve(platform, external_id)
    if linked is None:
        return
    sandbox_id, user, allowed = linked
    try:
        if not permitted(platform, external_id, author, allowed):
            logger.info("chat command refused", extra={"platform": platform, "channel": external_id, "author": author})
            await send(f"You aren't allowed to command this sandbox. Ask its owner to add your user ID ({author}).")
            return
        command = text.strip().lower()
        if command in ("help", "/help"):
            await send(HELP)
            return
        if command == "stop":
            await send("Stopping." if agent.stop(sandbox_id) else "Nothing is running.")
            return
        if command == "reset":
            await send("Conversation cleared." if agent.clear(sandbox_id) else "Stop the current task first.")
            return
        try:
            run = agent.start(user, sandbox_id, text, platform)
        except HTTPException as e:
            await send(f"⚠️ {e.detail}")
            return
        if edit is not None:
            await stream_edits(run, send, edit, limit)
        else:
            await stream_messages(run, send, limit)
    except Exception as e:
        metrics.error("chat", platform=platform)
        logger.error("chat relay failed", extra={"platform": platform, "sandbox_id": sandbox_id, "error": repr(e)})


async def stream_edits(run, send, edit, limit: int):
    message = await send("Working…")
    events, last = [], 0.0
    async for event in run.stream():
        if event["type"] in ("action", "text", "error", "status"):
            events.append(event)
        if events and time.monotonic() - last >= EDIT_INTERVAL and event["type"] != "done":
            last = time.monotonic()
            await edit(message, render(events, limit - 2) + "\n…")
    await edit(message, render(events, limit) or "Done.")


async def stream_messages(run, send, limit: int):
    pending: list[dict] = []
    async for event in run.stream():
        if event["type"] in ("action", "text", "error", "status"):
            pending.append(event)
        if event["type"] in ("text", "error", "status", "done") and pending:
            await send(render(pending, limit))
            pending = []
