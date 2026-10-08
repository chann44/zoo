"""Slack Events API: messages in a linked channel drive that sandbox's agent. The reply goes in a thread and is
edited in place as the agent works.

Setup: create a Slack app with the `chat:write`, `channels:history` and `groups:history` bot scopes, subscribe
to the `message.channels` and `message.groups` bot events with the request URL `<api>/integrations/slack/events`,
install it, invite the bot to the channel and set SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET. Only the Slack user IDs
on the channel's allowlist (or everyone, with "*") can command the sandbox."""

import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request, Response

from integrations import relay

WEBHOOK_PATH = "/integrations/slack/events"
API = "https://slack.com/api"
LIMIT = 3900
MENTION = re.compile(r"<@[A-Z0-9]+>")
# requests older than this are refused, so a captured request can't be replayed later
MAX_AGE = 300


@dataclass(frozen=True)
class Incoming:
    event_id: str
    channel: str
    thread: str
    user: str
    text: str


def configured() -> bool:
    return bool(os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_SIGNING_SECRET"))


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "v0=" + hmac.new(secret.encode(), f"v0:{timestamp}:".encode() + body, hashlib.sha256).hexdigest()


def verify(request: Request, body: bytes):
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "0")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > MAX_AGE:
        raise HTTPException(status_code=401, detail="stale request")
    expected = sign(os.environ["SLACK_SIGNING_SECRET"], timestamp, body)
    if not hmac.compare_digest(expected, request.headers.get("X-Slack-Signature", "")):
        raise HTTPException(status_code=401, detail="bad signature")


def incoming(payload: dict) -> Incoming | None:
    """The user message an event callback carries, or None for bot messages, edits, joins and other events."""
    event = payload.get("event") or {}
    if event.get("type") not in ("message", "app_mention") or event.get("bot_id") or event.get("subtype"):
        return None
    channel, ts = event.get("channel"), event.get("ts")
    if not channel or not ts:
        return None
    text = MENTION.sub("", event.get("text", "")).strip()
    if not text:
        return None
    # a message that mentions the bot arrives as both `message` and `app_mention`; key on the message itself
    return Incoming(f"{channel}:{ts}", channel, event.get("thread_ts") or ts, event.get("user", ""), text)


async def call(method: str, payload: dict) -> dict:
    async def once() -> dict:
        async with relay.client() as client:
            response = await client.post(
                f"{API}/{method}", json=payload, headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise relay.Retryable(f"slack {method}: HTTP {response.status_code}", relay.retry_after(response))
        data = response.json()
        if not data.get("ok"):
            if data.get("error") == "ratelimited":
                raise relay.Retryable(f"slack {method}: ratelimited", relay.retry_after(response))
            raise RuntimeError(f"slack {method}: {data.get('error')}")
        return data

    return await relay.retry(once)


def register(app: FastAPI, agent):
    @app.post(WEBHOOK_PATH, include_in_schema=False)
    async def events(request: Request):
        if not configured():
            raise HTTPException(status_code=503, detail="Slack is not configured")
        body = await request.body()
        verify(request, body)
        payload = json.loads(body)
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge")}
        message = incoming(payload)
        if message is None or not relay.first_time("slack", message.event_id):
            return Response(status_code=200)

        async def send(text: str) -> str:
            return (
                await call("chat.postMessage", {"channel": message.channel, "thread_ts": message.thread, "text": text})
            )["ts"]

        async def edit(ts: str, text: str):
            await call("chat.update", {"channel": message.channel, "ts": ts, "text": text})

        relay.spawn(relay.handle(agent, "slack", message.channel, message.user, message.text, send, edit, LIMIT))
        return Response(status_code=200)
