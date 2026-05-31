"""
Slack Events API, slash command, and interactive approval handlers.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from slack_sdk.signature import SignatureVerifier
from slack_sdk.web.async_client import AsyncWebClient

from apps.social.reply_service import (
    REPLY_PROFILES,
    ReplyProfile,
    get_social_reply_service,
)
from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Slack Bot")

APPROVE_ACTION_ID = "approve_incident_action"
SLACK_REPLY_PROFILE = ReplyProfile(
    platform="slack",
    namespace="slack_context",
    user_metadata_key="user_id",
    system_prompt="""You are an operations assistant responding to Slack messages.
Always respond in Vietnamese.
- Keep replies concise, professional, and suitable for a team channel.
- Do not invent incident details, metrics, or remediation results.
- If information is missing, ask for the specific missing context.
- For incident analysis requests, suggest using /analyze-incident.""",
)


class SlackConfigurationError(RuntimeError):
    """Raised when a required Slack integration setting is missing."""


def _require_setting(value: str, env_name: str) -> str:
    if value:
        return value
    raise SlackConfigurationError(f"{env_name} is not configured")


def verify_slack_signature(body: bytes, headers: Mapping[str, str]) -> bool:
    """Verify a Slack request and fail clearly when the signing secret is absent."""
    signing_secret = _require_setting(
        settings.slack_signing_secret,
        "SLACK_SIGNING_SECRET",
    )
    return SignatureVerifier(signing_secret=signing_secret).is_valid_request(
        body,
        headers,
    )


def get_slack_client() -> AsyncWebClient:
    """Create a Slack client lazily so imports never trigger network activity."""
    token = _require_setting(settings.slack_bot_token, "SLACK_BOT_TOKEN")
    return AsyncWebClient(token=token)


async def _verified_body(request: Request) -> bytes:
    body = await request.body()
    try:
        verified = verify_slack_signature(body, request.headers)
    except SlackConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if not verified:
        logger.warning("Invalid Slack request signature")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return body


def _parse_form_body(body: bytes) -> dict[str, str]:
    values = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: items[-1] for key, items in values.items()}


def _ensure_slack_reply_profile() -> None:
    # SocialReplyService owns the shared behavior; Slack contributes its profile lazily.
    REPLY_PROFILES.setdefault("slack", SLACK_REPLY_PROFILE)


async def generate_reply(user_message: str, user_id: str) -> str:
    """Generate a Slack reply through the shared social reply service."""
    _ensure_slack_reply_profile()
    return await get_social_reply_service().generate_reply(
        platform="slack",
        user_message=user_message,
        user_id=user_id,
    )


async def send_slack_message(
    channel: str,
    text: str,
    *,
    blocks: Optional[list[dict[str, Any]]] = None,
    thread_ts: Optional[str] = None,
) -> Any:
    """Send a Slack message using a lazily-created SDK client."""
    payload: dict[str, Any] = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    if thread_ts:
        payload["thread_ts"] = thread_ts
    return await get_slack_client().chat_postMessage(**payload)


async def call_gateway(
    method: str,
    path: str,
    *,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Call an authenticated Gateway endpoint."""
    gateway_url = _require_setting(settings.gateway_service_url, "GATEWAY_SERVICE_URL")
    api_key = _require_setting(settings.api_secret_key, "API_SECRET_KEY")
    url = f"{gateway_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=settings.agent_http_timeout_seconds) as client:
        response = await client.request(method, url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Gateway returned a non-object response")
    return data


def build_incident_gateway_request(
    text: str,
    channel_id: str,
    user_id: str,
) -> tuple[str, dict[str, Any]]:
    """Use the structured incident endpoint for JSON and /execute for free text."""
    session_id = f"slack:{channel_id}:{user_id}"
    try:
        incident_data = json.loads(text)
    except json.JSONDecodeError:
        incident_data = None

    if isinstance(incident_data, dict):
        return (
            "/incident/analyze",
            {"incident_data": incident_data, "session_id": session_id},
        )
    return (
        "/execute",
        {
            "user_input": f"Analyze this incident: {text}",
            "session_id": session_id,
        },
    )


def find_approval_id(value: Any) -> Optional[str]:
    """Find approval metadata returned by Gateway or a synthesized response."""
    if isinstance(value, dict):
        approval_id = value.get("approval_id")
        if isinstance(approval_id, str) and approval_id:
            return approval_id

        approval = value.get("approval")
        if isinstance(approval, dict):
            nested_id = approval.get("id") or approval.get("approval_id")
            if isinstance(nested_id, str) and nested_id:
                return nested_id

        for item in value.values():
            nested_id = find_approval_id(item)
            if nested_id:
                return nested_id
        return None

    if isinstance(value, list):
        for item in value:
            nested_id = find_approval_id(item)
            if nested_id:
                return nested_id
        return None

    if isinstance(value, str):
        match = re.search(
            r"\bapproval(?:_id|\s+id)?\s*[:=]\s*[`'\"]?([A-Za-z0-9_-]+)",
            value,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1)
    return None


def _slack_mrkdwn(text: str, limit: int = 2900) -> str:
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if len(escaped) <= limit:
        return escaped
    return escaped[: limit - 3] + "..."


def format_gateway_result(data: dict[str, Any]) -> str:
    """Return a readable Slack summary for a Gateway response."""
    value = data.get("result") or data.get("error") or data
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def build_incident_result_blocks(
    data: dict[str, Any],
    approval_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Render Gateway output as Slack blocks with an approval action when possible."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Incident analysis"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": _slack_mrkdwn(format_gateway_result(data)),
            },
        },
    ]
    if approval_id:
        blocks.extend(
            [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Approval required: `{approval_id}`",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Approve"},
                            "style": "primary",
                            "action_id": APPROVE_ACTION_ID,
                            "value": approval_id,
                            "confirm": {
                                "title": {
                                    "type": "plain_text",
                                    "text": "Approve action?",
                                },
                                "text": {
                                    "type": "mrkdwn",
                                    "text": "Approve this guarded incident action?",
                                },
                                "confirm": {"type": "plain_text", "text": "Approve"},
                                "deny": {"type": "plain_text", "text": "Cancel"},
                            },
                        }
                    ],
                },
            ]
        )
    return blocks


async def _analyze_incident_and_post_result(
    channel_id: str,
    user_id: str,
    text: str,
) -> None:
    try:
        path, payload = build_incident_gateway_request(text, channel_id, user_id)
        data = await call_gateway("POST", path, payload=payload)
        approval_id = find_approval_id(data)
        blocks = build_incident_result_blocks(data, approval_id)
        await send_slack_message(
            channel_id,
            format_gateway_result(data),
            blocks=blocks,
        )
    except Exception as exc:
        logger.error("Slack incident analysis failed: %s", exc, exc_info=True)
        error_text = f"Incident analysis failed: {exc}"
        try:
            await send_slack_message(
                channel_id,
                error_text,
                blocks=build_incident_result_blocks({"error": error_text}),
            )
        except Exception:
            logger.exception("Failed to post Slack incident analysis error")


@app.post("/webhook")
async def receive_slack_event(request: Request):
    """Receive signed Slack Events API callbacks and reply to user messages."""
    body = await _verified_body(request)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slack webhook body must be valid JSON",
        ) from exc

    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge", "")}

    event = data.get("event") or {}
    if (
        data.get("type") != "event_callback"
        or event.get("type") != "message"
        or event.get("subtype")
        or event.get("bot_id")
    ):
        return {"status": "ok", "handled": False}

    text = event.get("text")
    channel_id = event.get("channel")
    user_id = event.get("user")
    if not text or not channel_id or not user_id:
        return {"status": "ok", "handled": False, "reason": "missing_message_fields"}

    try:
        reply = await generate_reply(text, user_id)
        await send_slack_message(
            channel_id,
            reply,
            thread_ts=event.get("thread_ts") or event.get("ts"),
        )
    except SlackConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception:
        logger.exception("Error processing Slack message")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Slack message processing failed",
        )

    return {"status": "ok", "handled": True}


@app.post("/commands/analyze-incident")
async def analyze_incident_command(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Queue incident analysis requested through /analyze-incident."""
    body = await _verified_body(request)
    form = _parse_form_body(body)
    if form.get("command") != "/analyze-incident":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported Slack command",
        )

    text = form.get("text", "").strip()
    channel_id = form.get("channel_id", "")
    user_id = form.get("user_id", "")
    if not text or not channel_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="/analyze-incident requires text, channel_id, and user_id",
        )

    try:
        _require_setting(settings.slack_bot_token, "SLACK_BOT_TOKEN")
        _require_setting(settings.gateway_service_url, "GATEWAY_SERVICE_URL")
    except SlackConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    background_tasks.add_task(
        _analyze_incident_and_post_result,
        channel_id,
        user_id,
        text,
    )
    return {
        "response_type": "ephemeral",
        "text": "Incident analysis queued. The result will be posted in this channel.",
    }


@app.post("/interactions")
async def handle_slack_interaction(request: Request):
    """Approve a guarded Gateway action from a signed Slack block interaction."""
    body = await _verified_body(request)
    form = _parse_form_body(body)
    try:
        payload = json.loads(form.get("payload", ""))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slack interaction payload must be valid JSON",
        ) from exc

    action = next(
        (
            item
            for item in payload.get("actions", [])
            if item.get("action_id") == APPROVE_ACTION_ID
        ),
        None,
    )
    approval_id = action.get("value") if action else None
    if not approval_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported Slack interaction",
        )

    user_id = (payload.get("user") or {}).get("id", "unknown")
    try:
        await call_gateway("POST", f"/approvals/{approval_id}/approve")
    except Exception as exc:
        logger.error("Slack approval failed for %s: %s", approval_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gateway approval failed: {exc}",
        ) from exc

    return {
        "response_type": "ephemeral",
        "replace_original": False,
        "text": f"Approval `{approval_id}` submitted by <@{user_id}>.",
    }


@app.get("/health")
async def health():
    """Return Slack integration configuration status without exposing secrets."""
    configured = bool(settings.slack_bot_token and settings.slack_signing_secret)
    return {
        "status": "ok" if configured else "degraded",
        "service": "slack_bot",
        "configured": configured,
    }


if __name__ == "__main__":
    import uvicorn
    from shared.config import get_bind_host

    uvicorn.run(
        "apps.social.slack:app",
        host=get_bind_host(),
        port=8002,
        reload=False,
    )
