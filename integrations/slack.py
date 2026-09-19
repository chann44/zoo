import os
import requests
from fastapi import Request, Response


SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "xoxb-your-slack-bot-token")

SOURCE_CHANNEL_ID = "C_SOURCE_CHANNEL_ID"
TARGET_CHANNEL_ID = "C_TARGET_CHANNEL_ID"


async def receive_slack_events(request: Request):
    payload = await request.json()

    if "challenge" in payload:
        return {"challenge": payload["challenge"]}

    event = payload.get("event", {})

    event_type = event.get("type")
    channel_id = event.get("channel")
    text_content = event.get("text")
    user_id = event.get("user")

    if (
        event_type == "message"
        and channel_id == SOURCE_CHANNEL_ID
        and "bot_id" not in event
        and "subtype" not in event
    ):
        print(f"📩 New message intercepted in Source Channel: {text_content}")

        slack_url = "https://slack.com"
        headers = {
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json",
        }

        slack_payload = {
            "channel": TARGET_CHANNEL_ID,
            "text": f"*Forwarded from <#{SOURCE_CHANNEL_ID}> by <@{user_id}>:*\n> {text_content}",
        }

        response = requests.post(slack_url, json=slack_payload, headers=headers).json()

        if response.get("ok"):
            print("Successfully mirrored to Target Channel!")
        else:
            print(f" Slack API Error: {response.get('error')}")

    return Response(status_code=200)
