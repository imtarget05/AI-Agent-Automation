"""
Facebook Messenger Webhook Handler
Receives messages from Facebook and auto-generates replies using AI
"""
import hmac
import hashlib
import json
import logging
import httpx
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, status
from pydantic import BaseModel

from shared.config import get_settings
from shared.llm import get_llm_router
from shared.memory import get_session_memory, get_long_term_memory

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Facebook Bot")


# ──── Models ────

class FacebookMessage(BaseModel):
    """Incoming Facebook message"""
    sender_id: str
    recipient_id: str
    text: str
    timestamp: int


# ──── Verification ────

def verify_webhook_signature(signature: str, payload: str) -> bool:
    """Verify webhook came from Facebook"""
    expected_signature = hmac.new(
        settings.fb_verify_token.encode(),
        payload.encode(),
        hashlib.sha1
    ).hexdigest()
    return hmac.compare_digest(signature, expected_signature)


# ──---- Webhook Routes ----

@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = None,
    hub_verify_token: str = None,
    hub_challenge: str = None,
):
    """
    Facebook GET request to verify webhook
    """
    if hub_verify_token != settings.fb_verify_token:
        logger.warning(f"Invalid verify token: {hub_verify_token}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    logger.info("✅ Facebook webhook verified")
    return int(hub_challenge)


@app.post("/webhook")
async def receive_facebook_message(request: Request):
    """
    Receive incoming messages from Facebook Messenger
    """
    body = await request.json()

    logger.info(f"📨 Received Facebook webhook: {json.dumps(body, indent=2)}")

    # Process each entry
    for entry in body.get("entry", []):
        for messaging_event in entry.get("messaging", []):
            # Skip if no message
            if "message" not in messaging_event:
                continue

            sender_id = messaging_event["sender"]["id"]
            recipient_id = messaging_event["recipient"]["id"]
            message_data = messaging_event.get("message", {})

            # Only process text messages
            if "text" not in message_data:
                logger.info(f"Skipping non-text message from {sender_id}")
                continue

            user_message = message_data["text"]

            logger.info(f"💬 Message from {sender_id}: {user_message}")

            # Generate AI reply (non-blocking)
            try:
                reply = await generate_reply(user_message, sender_id)
                await send_facebook_message(sender_id, reply)
                logger.info(f"✅ Reply sent to {sender_id}")

            except Exception as e:
                logger.error(f"❌ Error processing message: {e}", exc_info=True)
                # Send fallback message
                await send_facebook_message(
                    sender_id,
                    "Xin lỗi, tôi đang gặp vấn đề. Vui lòng thử lại sau."
                )

    return {"status": "ok"}


# ──---- Reply Generation ----

FACEBOOK_SYSTEM_PROMPT = """You are a friendly customer service representative for an online shop.
Your role is to:
- Answer customer questions about products, pricing, and policies
- Help with order inquiries
- Suggest products based on customer interests
- Be professional but warm and conversational
- Keep responses concise (under 160 characters when possible for SMS-like feel)
- Always respond in Vietnamese

Important guidelines:
- If you don't know the answer, admit it and offer to escalate to a human
- Don't make up product information
- Be helpful and patient
- If customer asks for a discount, mention our current promotions or offer to connect them with sales team"""


async def generate_reply(user_message: str, sender_id: str) -> str:
    """
    Generate AI reply using LLM with conversation context
    """
    llm_router = get_llm_router()
    session_memory = get_session_memory(sender_id)  # Use sender_id as session
    long_term_memory = get_long_term_memory()

    # Get conversation history
    history = await session_memory.get_messages()

    # Search long-term memory for relevant context
    context_results = await long_term_memory.search(
        query=user_message,
        limit=3,
        namespace="facebook_context"
    )

    context_text = ""
    if context_results:
        context_text = "\n\nRelevant context:\n" + "\n".join([
            f"- {r['text']}"
            for r in context_results
        ])

    # Build messages for LLM
    messages = [
        {"role": "system", "content": FACEBOOK_SYSTEM_PROMPT + context_text},
        *history,  # Include conversation history
        {"role": "user", "content": user_message}
    ]

    # Generate reply
    reply = await llm_router.chat(
        messages=messages,
        task="classification",  # Use cheap model for chat
        temperature=0.7,
        max_tokens=200,
    )

    # Save to session memory
    await session_memory.append("user", user_message)
    await session_memory.append("assistant", reply)

    # Save to long-term memory for context
    await long_term_memory.save(
        text=f"Q: {user_message}\nA: {reply}",
        metadata={"platform": "facebook", "sender_id": sender_id},
        namespace="facebook_context"
    )

    return reply


# ──---- Send Message ----

async def send_facebook_message(recipient_id: str, text: str):
    """
    Send message back to Facebook user
    """
    url = f"https://graph.facebook.com/v18.0/me/messages"
    headers = {"Content-Type": "application/json"}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
                params={"access_token": settings.fb_page_token}
            )
            response.raise_for_status()
            logger.info(f"📤 Message sent to {recipient_id}")

        except httpx.HTTPError as e:
            logger.error(f"Failed to send Facebook message: {e}")
            raise


# ──---- Health Check ----

@app.get("/health")
async def health():
    return {"status": "ok", "service": "facebook_bot"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "facebook:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
    )
