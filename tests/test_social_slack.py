import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi.testclient import TestClient

import apps.social.slack as slack_module
from apps.social.slack import app

client = TestClient(app)


def _signed_headers(body: bytes, secret: str = "test-signing-secret") -> dict[str, str]:
    timestamp = str(int(time.time()))
    base = b"v0:" + timestamp.encode() + b":" + body
    signature = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
    }


def _json_request(data: dict) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(data, separators=(",", ":")).encode()
    return body, _signed_headers(body)


def _form_request(data: dict[str, str]) -> tuple[bytes, dict[str, str]]:
    body = urlencode(data).encode()
    return body, _signed_headers(body)


def test_slack_url_challenge_is_verified(monkeypatch):
    monkeypatch.setattr(
        slack_module.settings, "slack_signing_secret", "test-signing-secret"
    )
    body, headers = _json_request({"type": "url_verification", "challenge": "abc123"})

    response = client.post("/webhook", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"challenge": "abc123"}


def test_slack_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setattr(
        slack_module.settings, "slack_signing_secret", "test-signing-secret"
    )

    response = client.post(
        "/webhook",
        content=b'{"type":"url_verification","challenge":"abc123"}',
        headers={
            "X-Slack-Request-Timestamp": str(int(time.time())),
            "X-Slack-Signature": "v0=invalid",
        },
    )

    assert response.status_code == 403


def test_slack_webhook_fails_clearly_without_signing_secret(monkeypatch):
    monkeypatch.setattr(slack_module.settings, "slack_signing_secret", "")

    response = client.post("/webhook", content=b"{}")

    assert response.status_code == 503
    assert response.json()["detail"] == "SLACK_SIGNING_SECRET is not configured"


def test_slack_webhook_replies_to_text_message(monkeypatch):
    sent_messages = []

    async def fake_generate_reply(user_message: str, user_id: str) -> str:
        assert user_message == "Checkout dang loi"
        assert user_id == "U123"
        return "Da ghi nhan. Hay cung cap ma loi."

    async def fake_send_slack_message(channel: str, text: str, **kwargs):
        sent_messages.append((channel, text, kwargs))

    monkeypatch.setattr(
        slack_module.settings, "slack_signing_secret", "test-signing-secret"
    )
    monkeypatch.setattr(slack_module, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_module, "send_slack_message", fake_send_slack_message)
    body, headers = _json_request(
        {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U123",
                "channel": "C123",
                "text": "Checkout dang loi",
                "ts": "123.456",
            },
        }
    )

    response = client.post("/webhook", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["handled"] is True
    assert sent_messages == [
        (
            "C123",
            "Da ghi nhan. Hay cung cap ma loi.",
            {"thread_ts": "123.456"},
        )
    ]


def test_analyze_incident_command_uses_structured_endpoint_and_approval_blocks(
    monkeypatch,
):
    gateway_calls = []
    sent_messages = []

    async def fake_call_gateway(method: str, path: str, *, payload=None):
        gateway_calls.append((method, path, payload))
        return {
            "status": "completed",
            "result": "Deployment rollback requires operator approval.",
            "approval": {"id": "approval-123"},
        }

    async def fake_send_slack_message(channel: str, text: str, **kwargs):
        sent_messages.append((channel, text, kwargs))

    monkeypatch.setattr(
        slack_module.settings, "slack_signing_secret", "test-signing-secret"
    )
    monkeypatch.setattr(slack_module.settings, "slack_bot_token", "xoxb-test")
    monkeypatch.setattr(slack_module, "call_gateway", fake_call_gateway)
    monkeypatch.setattr(slack_module, "send_slack_message", fake_send_slack_message)
    body, headers = _form_request(
        {
            "command": "/analyze-incident",
            "channel_id": "C123",
            "user_id": "U123",
            "text": '{"service":"checkout","severity":"high"}',
        }
    )

    response = client.post("/commands/analyze-incident", content=body, headers=headers)

    assert response.status_code == 200
    assert gateway_calls == [
        (
            "POST",
            "/incident/analyze",
            {
                "incident_data": {"service": "checkout", "severity": "high"},
                "session_id": "slack:C123:U123",
            },
        )
    ]
    blocks = sent_messages[0][2]["blocks"]
    assert blocks[-1]["type"] == "actions"
    assert blocks[-1]["elements"][0]["value"] == "approval-123"


def test_analyze_incident_command_uses_execute_for_free_text(monkeypatch):
    gateway_calls = []

    async def fake_call_gateway(method: str, path: str, *, payload=None):
        gateway_calls.append((method, path, payload))
        return {"status": "success", "result": "Analysis complete."}

    async def fake_send_slack_message(channel: str, text: str, **kwargs):
        return None

    monkeypatch.setattr(
        slack_module.settings, "slack_signing_secret", "test-signing-secret"
    )
    monkeypatch.setattr(slack_module.settings, "slack_bot_token", "xoxb-test")
    monkeypatch.setattr(slack_module, "call_gateway", fake_call_gateway)
    monkeypatch.setattr(slack_module, "send_slack_message", fake_send_slack_message)
    body, headers = _form_request(
        {
            "command": "/analyze-incident",
            "channel_id": "C123",
            "user_id": "U123",
            "text": "checkout tra ve 500 sau deploy",
        }
    )

    response = client.post("/commands/analyze-incident", content=body, headers=headers)

    assert response.status_code == 200
    assert gateway_calls == [
        (
            "POST",
            "/execute",
            {
                "user_input": "Analyze this incident: checkout tra ve 500 sau deploy",
                "session_id": "slack:C123:U123",
            },
        )
    ]


def test_slack_approval_button_calls_gateway(monkeypatch):
    gateway_calls = []

    async def fake_call_gateway(method: str, path: str, *, payload=None):
        gateway_calls.append((method, path, payload))
        return {"status": "approved"}

    monkeypatch.setattr(
        slack_module.settings, "slack_signing_secret", "test-signing-secret"
    )
    monkeypatch.setattr(slack_module, "call_gateway", fake_call_gateway)
    payload = json.dumps(
        {
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": slack_module.APPROVE_ACTION_ID,
                    "value": "approval-123",
                }
            ],
        }
    )
    body, headers = _form_request({"payload": payload})

    response = client.post("/interactions", content=body, headers=headers)

    assert response.status_code == 200
    assert gateway_calls == [("POST", "/approvals/approval-123/approve", None)]
    assert "approval-123" in response.json()["text"]
