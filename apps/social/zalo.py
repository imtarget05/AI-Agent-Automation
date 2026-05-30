"""
Zalo OA Auto-reply Handler
Receives messages from Zalo Official Account and auto-generates replies
"""
import json
import logging
import httpx
import hmac
import hashlib
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, status
from pydantic import BaseModel

from shared.config import get_settings
from shared.llm import get_llm_router
from shared.memory import get_session_memory, get_long_term_memory

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Zalo Bot")


# ──── Models ----

class ZaloMessage(BaseModel):
    """Incoming Zalo message"""
    user_id: str
    oa_id: str
    text: str
    timestamp: int


# ──---- Webhook Routes ----

def verify_zalo_signature(data: str, signature: str) -> bool:
    """Verify webhook signature from Zalo"""
    if not settings.zalo_server_key:
        logger.warning("ZALO_SERVER_KEY not configured")
        return False

    expected_signature = hmac.new(
        settings.zalo_server_key.encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature, expected_signature)


@app.post("/webhook")
async def receive_zalo_message(request: Request):
    """
    Receive incoming messages from Zalo OA
    """
    # Get raw body for signature verification
    body = await request.body()
    signature = request.headers.get("X-Zalo-Signature", "")

    # Verify signature
    if not verify_zalo_signature(body.decode(), signature):
        logger.warning("Invalid Zalo signature")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    data = json.loads(body)
    logger.info(f"📨 Received Zalo webhook: {json.dumps(data, indent=2)}")

    # Extract event type
    event_name = data.get("event_name")

    if event_name == "user_send_text":
        # Text message from user
        user_id = data["sender"]["id"]
        text = data["message"]["text"]

        logger.info(f"💬 Message from {user_id}: {text}")

        try:
            reply = await generate_reply(text, user_id)
            await send_zalo_message(user_id, reply)
            logger.info(f"✅ Reply sent to {user_id}")

        except Exception as e:
            logger.error(f"❌ Error processing Zalo message: {e}", exc_info=True)

    elif event_name == "user_send_file":
        # User sent file/image
        logger.info(f"📁 User {data['sender']['id']} sent file")
        await send_zalo_message(
            data["sender"]["id"],
            "Cảm ơn bạn đã gửi tệp. Chúng tôi sẽ xử lý trong sớm nhất."
        )

    return {"status": "ok"}


# ──---- Reply Generation ----

ZALO_SYSTEM_PROMPT = """Bạn là nhân viên chăm sóc khách hàng thân thiện của một cửa hàng trực tuyến.
Hãy:
- Trả lời câu hỏi về sản phẩm, giá cả, chính sách
- Hỗ trợ tìm kiếm sản phẩm
- Đề xuất sản phẩm phù hợp
- Giữ phong cách chuyên nghiệp nhưng thân thiện
- Giữ câu trả lời ngắn gọn
- Lúc nào cũng trả lời bằng Tiếng Việt

Quy tắc quan trọng:
- Nếu không biết, hãy nói thẳng và liên hệ thêm
- Không bịa chuyện về sản phẩm
- Lúc nào cũng hỗ trợ khách hàng
- Nếu khách hỏi giảm giá, hãy nhắc đến chương trình khuyến mại hiện tại"""


async def generate_reply(user_message: str, user_id: str) -> str:
    """
    Generate AI reply for Zalo message
    """
    llm_router = get_llm_router()
    session_memory = get_session_memory(user_id)
    long_term_memory = get_long_term_memory()

    # Get conversation history
    history = await session_memory.get_messages()

    # Search long-term memory
    context_results = await long_term_memory.search(
        query=user_message,
        limit=3,
        namespace="zalo_context"
    )

    context_text = ""
    if context_results:
        context_text = "\n\nThông tin liên quan:\n" + "\n".join([
            f"- {r['text']}"
            for r in context_results
        ])

    messages = [
        {"role": "system", "content": ZALO_SYSTEM_PROMPT + context_text},
        *history,
        {"role": "user", "content": user_message}
    ]

    # Generate reply
    reply = await llm_router.chat(
        messages=messages,
        task="classification",
        temperature=0.7,
        max_tokens=200,
    )

    # Save to memory
    await session_memory.append("user", user_message)
    await session_memory.append("assistant", reply)
    await long_term_memory.save(
        text=f"Q: {user_message}\nA: {reply}",
        metadata={"platform": "zalo", "user_id": user_id},
        namespace="zalo_context"
    )

    return reply


# ──---- Send Message ----

async def send_zalo_message(user_id: str, text: str):
    """
    Send message to Zalo user
    """
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
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            logger.info(f"📤 Zalo message sent to {user_id}")

        except httpx.HTTPError as e:
            logger.error(f"Failed to send Zalo message: {e}")
            raise


# ──---- Health Check ----

@app.get("/health")
async def health():
    return {"status": "ok", "service": "zalo_bot"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "zalo:app",
        host="0.0.0.0",
        port=8002,
        reload=False,
    )
