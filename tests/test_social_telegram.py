from fastapi.testclient import TestClient

from apps.social.telegram import app
import apps.social.telegram as telegram_module

client = TestClient(app)


def test_telegram_webhook_replies_to_text(monkeypatch):
    sent_messages = []

    async def fake_generate_reply(user_message: str, user_id: str) -> str:
        assert user_message == "Xin chao"
        assert user_id == "12345"
        return "Chao ban, toi co the giup gi?"

    async def fake_send_telegram_message(chat_id: int, text: str):
        sent_messages.append((chat_id, text))

    monkeypatch.setattr(telegram_module, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(
        telegram_module, "send_telegram_message", fake_send_telegram_message
    )

    response = client.post(
        "/webhook",
        json={
            "message": {
                "message_id": 1,
                "chat": {"id": 98765},
                "from": {"id": 12345},
                "text": "Xin chao",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["handled"] is True
    assert sent_messages == [(98765, "Chao ban, toi co the giup gi?")]


def test_telegram_webhook_ignores_non_text_updates(monkeypatch):
    async def fake_send_telegram_message(chat_id: int, text: str):
        raise AssertionError("send_telegram_message should not be called")

    monkeypatch.setattr(
        telegram_module, "send_telegram_message", fake_send_telegram_message
    )

    response = client.post(
        "/webhook",
        json={
            "message": {
                "message_id": 1,
                "chat": {"id": 98765},
                "from": {"id": 12345},
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["handled"] is False
