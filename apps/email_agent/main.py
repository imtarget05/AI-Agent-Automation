"""
Email Agent Service - FastAPI microservice for high-level email composition and dispatch.
Uses the cost-optimized LLMRouter to compose contextual emails based on incident information and desired tone.
"""

import json
import logging
from typing import Dict, Any, Optional
import httpx
from fastapi import FastAPI, Body, HTTPException
from contextlib import asynccontextmanager

from shared.config import get_settings
from shared.llm import get_llm_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("email_agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("📧 Starting Email Agent microservice")
    yield
    logger.info("🛑 Shutting down Email Agent")


app = FastAPI(
    title="Multi-Agent AIOps Email Agent",
    description="High-level agent for composing incident reports and notification emails with tailored tones",
    version="1.0.0",
    lifespan=lifespan,
)

llm_router = get_llm_router()
settings = get_settings()

EMAIL_COMPOSER_PROMPT = """You are an expert AIOps Communications Agent.
Your job is to draft a professional email regarding a system incident or operational request.

You will be provided with:
1. Tone required (e.g., formal, short_summary, executive_summary, non_technical).
2. Context about the incident (logs, metrics, pods, events).
3. The core instructions/actions to report.

Tone guidelines:
- formal: Complete root cause explanation, technical specifics (HikariPool timeouts, OOM warnings), impact, and proposed resolution. Highly technical and structured.
- short_summary: Clear, bulleted breakdown of the incident, impact, and action items. Brief and highly scannable.
- executive_summary: High-level overview explaining the business impact, cost implication, security clearance, and direct recovery steps. Focus on SLA metrics and minimal jargon.
- non_technical: Simple analogies (e.g., "the digital gateway was overloaded," "the database connection line was full"), friendly tone, reassuring next steps, no deep code stack traces.

Always output a JSON-wrapped response with keys:
"subject": A highly polished subject line.
"body": The fully formatted body of the email. HTML formatted (using simple, professional inline styles, clean tables, and bold highlights).

Write the email now. Return ONLY raw JSON. No markdown blocks.
"""


@app.get("/health")
def health():
    return {"status": "ok", "service": "email_agent"}


async def send_composed_email(
    recipient: str,
    subject: str,
    body: str,
    approval_id: Optional[str],
) -> Dict[str, Any]:
    """Send through the guarded tool registry so the agent cannot bypass approval."""
    url = f"{settings.tool_service_url.rstrip('/')}/email/send"
    try:
        async with httpx.AsyncClient(
            timeout=settings.agent_http_timeout_seconds
        ) as client:
            response = await client.post(
                url,
                json={
                    "to_address": recipient,
                    "subject": subject,
                    "body": body,
                    "is_html": True,
                    "approval_id": approval_id,
                },
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Tool service unavailable: {exc}",
        ) from exc


@app.post("/execute")
async def execute_task(
    instruction: str = Body(..., description="Email drafting instruction"),
    recipient: str = Body(..., description="Target email recipient"),
    tone: str = Body(
        "formal",
        description="Composition tone: formal, short_summary, executive_summary, non_technical",
    ),
    context_data: Optional[Dict[str, Any]] = Body(
        None, description="System incident metrics, logs, etc."
    ),
    approval_id: Optional[str] = Body(
        None, description="Operator approval returned by the Gateway"
    ),
    mode: str = Body(
        "draft", description="Execution mode: draft, send_after_approval, send_now"
    ),
):
    """
    Execute high-level email composition task.
    Drafts the email via LLM and optionally submits it to the guarded tool registry.
    """
    logger.info(
        f"Email Agent received task: {instruction} (Tone: {tone}, Mode: {mode})"
    )

    prompt = (
        f"INSTRUCTION: {instruction}\n"
        f"RECIPIENT: {recipient}\n"
        f"TONE: {tone}\n"
        f"CONTEXT DATA:\n{context_data or 'No context data provided.'}"
    )

    try:
        # Generate the email draft using LLM Router
        response_str = await llm_router.chat(
            messages=[
                {"role": "system", "content": EMAIL_COMPOSER_PROMPT},
                {"role": "user", "content": prompt},
            ],
            task="summarize",  # Cheap & fast cost routing
        )

        # Clean response string if LLM returned markdown blocks
        clean_str = response_str.strip()
        if "{" in clean_str and "}" in clean_str:
            start = clean_str.find("{")
            end = clean_str.rfind("}")
            clean_str = clean_str[start : end + 1]

        # Parse JSON output from LLM safely
        try:
            email_data = json.loads(clean_str)
            subject = email_data.get("subject", "AIOps Platform Notification")
            body = email_data.get("body", "No content generated.")
        except Exception as json_err:
            logger.warning(
                f"Failed to parse LLM response as JSON: {json_err}. Using fallback parsing."
            )
            # Fallback parsing in case JSON is malformed
            subject = f"AIOps Alert: {instruction[:50]}..."
            body = response_str

        if mode == "draft":
            return {
                "success": True,
                "agent": "email_agent",
                "mode": "draft",
                "subject": subject,
                "composed_body": body,
                "message": "Email draft created successfully. To send, use mode='send_now' or 'send_after_approval'.",
            }

        # Submit the composed email through the guarded tool registry
        send_result = await send_composed_email(
            recipient=recipient,
            subject=subject,
            body=body,
            approval_id=approval_id,
        )

        return {
            "success": send_result.get("success", False),
            "agent": "email_agent",
            "mode": mode,
            "subject": subject,
            "composed_body": body,
            "requires_approval": send_result.get("requires_approval", False),
            "send_result": send_result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing Email Agent task: {e}")
        raise HTTPException(status_code=500, detail=str(e))
