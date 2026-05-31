"""
Facebook Messenger webhook handler.
"""

import hashlib
import hmac
import json
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel

from apps.social.reply_service import get_social_reply_service
from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Facebook Bot")


class FacebookMessage(BaseModel):
    """Incoming Facebook message."""

    sender_id: str
    recipient_id: str
    text: str
    timestamp: int


def verify_webhook_signature(signature: str, payload: bytes) -> bool:
    """Verify a Facebook POST webhook when an app secret is configured."""
    if not settings.fb_app_secret:
        return True
    if not signature:
        return False

    expected_signature = (
        "sha256="
        + hmac.new(
            settings.fb_app_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(signature, expected_signature)


@app.get("/webhook")
async def verify_webhook(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """Handle Facebook GET webhook verification."""
    if hub_mode != "subscribe" or hub_verify_token != settings.fb_verify_token:
        logger.warning("Invalid Facebook webhook verification request")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    logger.info("Facebook webhook verified")
    return hub_challenge or ""


@app.post("/webhook")
async def receive_facebook_message(request: Request):
    """Receive incoming Facebook Messenger messages."""
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_webhook_signature(signature, raw_body):
        logger.warning("Invalid Facebook webhook signature")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    body = json.loads(raw_body)
    logger.info("Received Facebook webhook: %s", json.dumps(body, indent=2))

    for entry in body.get("entry", []):
        for messaging_event in entry.get("messaging", []):
            message_data = messaging_event.get("message")
            if not message_data:
                continue

            sender_id = messaging_event["sender"]["id"]
            if "text" not in message_data:
                logger.info("Skipping non-text message from %s", sender_id)
                continue

            user_message = message_data["text"]
            logger.info("Message from %s: %s", sender_id, user_message)

            try:
                reply = await generate_reply(user_message, sender_id)
                await send_facebook_message(sender_id, reply)
                logger.info("Reply sent to %s", sender_id)
            except Exception as exc:
                logger.error(
                    "Error processing Facebook message: %s", exc, exc_info=True
                )
                await send_facebook_message(
                    sender_id,
                    "Xin lỗi, hệ thống đang gặp vấn đề. Vui lòng thử lại sau.",
                )

    return {"status": "ok"}


async def generate_reply(user_message: str, sender_id: str) -> str:
    """Generate a Facebook reply through the shared social reply service."""
    return await get_social_reply_service().generate_reply(
        platform="facebook",
        user_message=user_message,
        user_id=sender_id,
    )


async def send_facebook_message(recipient_id: str, text: str):
    """Send a message to a Facebook user."""
    url = "https://graph.facebook.com/v18.0/me/messages"
    headers = {"Content-Type": "application/json"}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            url,
            headers=headers,
            json=payload,
            params={"access_token": settings.fb_page_token},
        )
        response.raise_for_status()
        logger.info("Facebook message sent to %s", recipient_id)


@app.get("/health")
async def health():
    """Return the Facebook bot health status."""
    return {"status": "ok", "service": "facebook_bot"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.social.facebook:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
    )
