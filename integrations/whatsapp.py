import os
import requests
from dotenv import load_dotenv
from pydantic import BaseModel
from fastapi import HTTPException, status, Query

load_dotenv()
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
API_KEY = os.getenv("INTERNAL_API_KEY")
WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN")


class WhatsAppMessage(BaseModel):
    agent_id: str
    recepeint_phone_number: str
    text: str


def agent_send_message(payload: WhatsAppMessage):
    url = f"https://facebook.com{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    meta_payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": payload.recipient_phone,
        "type": "text",
        "text": {"body": payload.message_text},
    }

    try:
        response = requests.post(url, headers=headers, json=meta_payload)
        response_data = response.json()

        if response.status_code == 200:
            return {
                "status": "success",
                "agent_id": payload.agent_id,
                "whatsapp_message_id": response_data.get("messages", [{}])[0].get("id"),
                "recipient": payload.recipient_phone,
            }
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Meta API Error: {response_data}",
            )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to process agent message: {str(e)}"
        )


def verify_webhook(mode: str, token: str, challenge: str):
    if mode and token:
        if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
            print(" Webhook verified successfully by Meta!")
            return challenge
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Verification token mismatch",
            )


async def postWebbok(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: int = Query(None, alias="hub.challenge"),
):
    if mode and token:
        if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
            print("Webhook verified successfully by Meta!")
            return challenge
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Verification token mismatch",
            )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Missing verification parameters",
    )


async def receive_whatsapp_event(payload):

    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})

        if "messages" in value:
            message_data = value["messages"][0]
            contact_data = value.get("contacts", [{}])[0]

            user_phone = message_data.get("from")  # Customer's WhatsApp ID/Phone
            profile_name = contact_data.get("profile", {}).get("name", "Unknown User")
            message_type = message_data.get("type")

            print(f"\n New Incoming Message from {profile_name} ({user_phone}):")

            if message_type == "text":
                text_body = message_data.get("text", {}).get("body")
                print(f"Text: {text_body}")

                # 1. Save this message to SQL/NoSQL Database.
                # 2. Forward it to agent .

            elif message_type == "image":
                image_id = message_data.get("image", {}).get("id")
                print(f" Received an Image (Meta Media ID: {image_id})")

            elif message_type == "document":
                doc_id = message_data.get("document", {}).get("id")
                print(f" Received a Document (Meta Media ID: {doc_id})")

        return {"status": "success"}

    except (IndexError, KeyError) as e:
        return {"status": "ignored_event_type"}
