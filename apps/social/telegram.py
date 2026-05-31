"""
Telegram bot webhook handler.
"""

from __future__ import annotations

import json
import logging

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from apps.social.reply_service import get_social_reply_service
from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Telegram Bot")


class TelegramChat(BaseModel):
    id: int


class TelegramUser(BaseModel):
    id: int


class TelegramMessage(BaseModel):
    message_id: int
    chat: TelegramChat
    from_user: TelegramUser | None = None
    text: str | None = None


def verify_telegram_signature(secret_token: str) -> bool:
    """Verify Telegram webhook secret token when configured."""
    if not settings.telegram_webhook_secret:
        return True
    return secret_token == settings.telegram_webhook_secret


@app.post("/webhook")
async def receive_telegram_update(request: Request):
    """Receive incoming Telegram updates and auto-reply to text messages."""
    secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not verify_telegram_signature(secret_token):
        logger.warning("Invalid Telegram webhook secret token")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    body = await request.body()
    data = json.loads(body)
    logger.info("Received Telegram update: %s", json.dumps(data, indent=2))

    message = data.get("message") or data.get("edited_message")
    if not message:
        return {"status": "ok", "handled": False}

    text = message.get("text")
    if not text:
        return {"status": "ok", "handled": False, "reason": "non_text_message"}

    chat_id = message["chat"]["id"]
    user_id = (message.get("from") or {}).get("id", chat_id)

    try:
        reply = await generate_reply(text, str(user_id))
        await send_telegram_message(chat_id, reply)
        logger.info("Reply sent to Telegram chat %s", chat_id)
        return {"status": "ok", "handled": True}
    except Exception as exc:
        logger.error("Error processing Telegram message: %s", exc, exc_info=True)
        await send_telegram_message(
            chat_id,
            "Xin lỗi, hệ thống đang gặp vấn đề. Vui lòng thử lại sau.",
        )
        return {"status": "ok", "handled": True, "fallback": True}


async def generate_reply(user_message: str, user_id: str) -> str:
    """Generate a Telegram reply through the shared social reply service."""
    return await get_social_reply_service().generate_reply(
        platform="telegram",
        user_message=user_message,
        user_id=user_id,
    )


async def send_telegram_message(chat_id: int, text: str):
    """Send a message to a Telegram chat."""
    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot token is not configured",
        )

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        logger.info("Telegram message sent to chat %s", chat_id)


@app.get("/health")
async def health():
    """Return the Telegram bot health status."""
    return {"status": "ok", "service": "telegram_bot"}


if __name__ == "__main__":
    import uvicorn
    from shared.config import get_bind_host

    uvicorn.run(
        "apps.social.telegram:app",
        host=get_bind_host(),
        port=8002,
        reload=False,
    )
