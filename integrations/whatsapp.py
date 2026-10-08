"""WhatsApp Cloud API: messages from a linked phone number drive that sandbox's agent. WhatsApp can't edit sent
messages, so the agent's progress arrives as one message per step.

Setup: in a Meta app with the WhatsApp product, set the webhook callback URL to `<api>/integrations/whatsapp/webhook`
with your verify token and subscribe to `messages`. Set WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID,
WHATSAPP_VERIFY_TOKEN and WHATSAPP_APP_SECRET. Link the sender's phone number in international format; only that
number can command the sandbox."""

import hashlib
import hmac
import json
import os

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from integrations import relay
from logger.logger import logger

WEBHOOK_PATH = "/integrations/whatsapp/webhook"
GRAPH = os.environ.get("WHATSAPP_GRAPH_URL", "https://graph.facebook.com/v21.0")
LIMIT = 4000


def configured() -> bool:
    return all(
        os.environ.get(k)
        for k in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET")
    )


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(request: Request, body: bytes):
    expected = sign(os.environ["WHATSAPP_APP_SECRET"], body)
    if not hmac.compare_digest(expected, request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(status_code=401, detail="bad signature")


async def send_text(to: str, text: str):
    async def once():
        async with relay.client() as client:
            response = await client.post(
                f"{GRAPH}/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages",
                headers={"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}"},
                json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}},
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise relay.Retryable(f"whatsapp send: HTTP {response.status_code}", relay.retry_after(response))
        if response.status_code >= 400:
            raise RuntimeError(f"whatsapp send failed: {response.text[:300]}")

    await relay.retry(once)


def messages_of(payload: dict) -> list[dict]:
    return [
        m
        for entry in payload.get("entry", [])
        for change in entry.get("changes", [])
        for m in (change.get("value") or {}).get("messages", [])
    ]


def register(app: FastAPI, agent):
    @app.get(WEBHOOK_PATH, include_in_schema=False)
    def subscribe(
        mode: str = Query("", alias="hub.mode"),
        token: str = Query("", alias="hub.verify_token"),
        challenge: str = Query("", alias="hub.challenge"),
    ):
        expected = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
        if mode != "subscribe" or not expected or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=403, detail="verification failed")
        return PlainTextResponse(challenge)

    @app.post(WEBHOOK_PATH, include_in_schema=False)
    async def receive(request: Request):
        if not configured():
            raise HTTPException(status_code=503, detail="WhatsApp is not configured")
        body = await request.body()
        verify(request, body)
        for message in messages_of(json.loads(body)):
            sender = message.get("from", "")
            if not sender or not relay.first_time("whatsapp", message.get("id", "")):
                continue
            if message.get("type") != "text":
                logger.info("ignored whatsapp message", extra={"type": message.get("type")})
                continue

            async def send(text: str, to: str = sender):
                await send_text(to, text)

            text = (message.get("text") or {}).get("body", "")
            relay.spawn(relay.handle(agent, "whatsapp", sender, sender, text, send, None, LIMIT))
        return Response(status_code=200)
