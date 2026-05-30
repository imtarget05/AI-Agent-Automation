"""
Zalo OA webhook handler.
"""

import hashlib
import hmac
import json
import logging

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from apps.social.reply_service import get_social_reply_service
from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Zalo Bot")


class ZaloMessage(BaseModel):
    """Incoming Zalo message."""

    user_id: str
    oa_id: str
    text: str
    timestamp: int


def verify_zalo_signature(data: str, signature: str) -> bool:
    """Verify a webhook signature from Zalo."""
    if not settings.zalo_server_key:
        logger.warning("ZALO_SERVER_KEY is not configured")
        return False

    expected_signature = hmac.new(
        settings.zalo_server_key.encode(),
        data.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected_signature)


@app.post("/webhook")
async def receive_zalo_message(request: Request):
    """Receive incoming messages from Zalo OA."""
    body = await request.body()
    signature = request.headers.get("X-Zalo-Signature", "")

    if not verify_zalo_signature(body.decode("utf-8"), signature):
        logger.warning("Invalid Zalo signature")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    data = json.loads(body)
    logger.info("Received Zalo webhook: %s", json.dumps(data, indent=2))

    event_name = data.get("event_name")
    if event_name == "user_send_text":
        user_id = data["sender"]["id"]
        text = data["message"]["text"]
        logger.info("Message from %s: %s", user_id, text)

        try:
            reply = await generate_reply(text, user_id)
            await send_zalo_message(user_id, reply)
            logger.info("Reply sent to %s", user_id)
        except Exception as exc:
            logger.error("Error processing Zalo message: %s", exc, exc_info=True)

    elif event_name == "user_send_file":
        user_id = data["sender"]["id"]
        logger.info("User %s sent a file", user_id)
        await send_zalo_message(
            user_id,
            "Cảm ơn bạn đã gửi tệp. Chúng tôi sẽ xử lý trong thời gian sớm nhất.",
        )

    return {"status": "ok"}


async def generate_reply(user_message: str, user_id: str) -> str:
    """Generate a Zalo reply through the shared social reply service."""
    return await get_social_reply_service().generate_reply(
        platform="zalo",
        user_message=user_message,
        user_id=user_id,
    )


async def send_zalo_message(user_id: str, text: str):
    """Send a message to a Zalo user."""
    url = "https://openapi.zalo.me/v3.0/oa/message/cs"
    headers = {
        "access_token": settings.zalo_oa_token,
        "Content-Type": "application/json",
    }
    payload = {
        "recipient": {"user_id": user_id},
        "message": {"text": text},
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info("Zalo message sent to %s", user_id)


@app.get("/health")
async def health():
    """Return the Zalo bot health status."""
    return {"status": "ok", "service": "zalo_bot"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.social.zalo:app",
        host="0.0.0.0",
        port=8002,
        reload=False,
    )
