"""Slack Events API: messages in a linked channel drive that sandbox's agent. The reply goes in a thread and is
edited in place as the agent works.

Setup: create a Slack app with the `chat:write`, `channels:history` and `groups:history` bot scopes, subscribe
to the `message.channels` and `message.groups` bot events with the request URL `<api>/integrations/slack/events`,
install it, invite the bot to the channel and set SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET."""

import asyncio
import hashlib
import hmac
import json
import os
import re
import time

import httpx
from fastapi import FastAPI, HTTPException, Request, Response

from integrations import relay

WEBHOOK_PATH = "/integrations/slack/events"
API = "https://slack.com/api"
LIMIT = 3900
MENTION = re.compile(r"<@[A-Z0-9]+>")

seen = relay.Seen()


def configured() -> bool:
    return bool(os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_SIGNING_SECRET"))


def verify(request: Request, body: bytes):
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "0")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300:
        raise HTTPException(status_code=401, detail="stale request")
    base = f"v0:{timestamp}:".encode() + body
    expected = "v0=" + hmac.new(os.environ["SLACK_SIGNING_SECRET"].encode(), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Slack-Signature", "")):
        raise HTTPException(status_code=401, detail="bad signature")


async def call(method: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{API}/{method}", json=payload, headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}
        )
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"slack {method}: {data.get('error')}")
    return data


def register(app: FastAPI, agent):
    tasks: set[asyncio.Task] = set()

    @app.post(WEBHOOK_PATH, include_in_schema=False)
    async def events(request: Request):
        if not configured():
            raise HTTPException(status_code=503, detail="Slack is not configured")
        body = await request.body()
        verify(request, body)
        payload = json.loads(body)
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge")}
        event = payload.get("event") or {}
        if (
            event.get("type") in ("message", "app_mention")
            and not event.get("bot_id")
            and not event.get("subtype")
            and seen.add(f"{event.get('channel')}:{event.get('ts')}")
        ):
            channel, thread = event["channel"], event.get("thread_ts") or event["ts"]
            text = MENTION.sub("", event.get("text", "")).strip()

            async def send(message: str) -> str:
                return (await call("chat.postMessage", {"channel": channel, "thread_ts": thread, "text": message}))[
                    "ts"
                ]

            async def edit(ts: str, message: str):
                await call("chat.update", {"channel": channel, "ts": ts, "text": message})

            if text:
                task = asyncio.create_task(relay.handle(agent, "slack", channel, text, send, edit, LIMIT))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        return Response(status_code=200)
