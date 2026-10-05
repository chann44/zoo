"""Shared plumbing for chat platforms: route an incoming message to the linked sandbox's agent and stream the
run back as the platform allows (one message edited in place, or a message per step)."""

import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

from fastapi import HTTPException

from db.connection import db_manager
from logger.logger import logger

HELP = "Send a task and I'll do it on the sandbox desktop. `stop` cancels the current task, `reset` clears the conversation."
EDIT_INTERVAL = 1.2


class Seen:
    """Remembers recent message IDs so platform retries don't start a task twice."""

    def __init__(self, size: int = 512):
        self.ids: OrderedDict[str, None] = OrderedDict()
        self.size = size

    def add(self, key: str) -> bool:
        if key in self.ids:
            return False
        self.ids[key] = None
        if len(self.ids) > self.size:
            self.ids.popitem(last=False)
        return True


def render(events: list[dict], limit: int) -> str:
    lines = []
    for e in events:
        if e["type"] == "text":
            lines.append(e["text"])
        elif e["type"] == "action":
            lines.append(f"› {e['text']}")
        elif e["type"] == "error":
            lines.append(f"⚠️ {e['text']}")
    text = "\n".join(lines).strip()
    return text if len(text) <= limit else "…" + text[-(limit - 1) :]


def resolve(platform: str, external_id: str):
    """Returns (sandbox_id, user) for a linked channel, or None."""
    with db_manager.session() as db:
        channel = db.get_agent_channel(platform=platform, external_id=external_id)
        if channel is None:
            return None
        return channel.sandbox_id, db.get_user(id=channel.created_by)


async def handle(
    agent,
    platform: str,
    external_id: str,
    text: str,
    send: Callable[[str], Awaitable[object]],
    edit: Callable[[object, str], Awaitable[None]] | None,
    limit: int,
):
    """Runs one incoming chat message. With `edit`, the reply is a single message updated as the agent works;
    without it, each assistant message and the actions before it go out as new messages."""
    linked = resolve(platform, external_id)
    if linked is None:
        return
    sandbox_id, user = linked
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
    try:
        if edit is not None:
            await stream_edits(run, send, edit, limit)
        else:
            await stream_messages(run, send, limit)
    except Exception as e:
        logger.error("chat relay failed", extra={"platform": platform, "sandbox_id": sandbox_id, "error": repr(e)})


async def stream_edits(run, send, edit, limit: int):
    message = await send("Working…")
    events, last = [], 0.0
    async for event in run.stream():
        if event["type"] in ("action", "text", "error"):
            events.append(event)
        if events and time.monotonic() - last >= EDIT_INTERVAL and event["type"] != "done":
            last = time.monotonic()
            await edit(message, render(events, limit - 2) + "\n…")
    await edit(message, render(events, limit) or "Done.")


async def stream_messages(run, send, limit: int):
    pending: list[dict] = []
    async for event in run.stream():
        if event["type"] in ("action", "text", "error"):
            pending.append(event)
        if event["type"] in ("text", "error", "done") and pending:
            await send(render(pending, limit))
            pending = []
