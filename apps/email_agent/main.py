"""
Email Agent Service - FastAPI microservice for high-level email composition and dispatch.
Uses the cost-optimized LLMRouter to compose contextual emails based on incident information and desired tone.
"""

import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, Body, HTTPException
from contextlib import asynccontextmanager

from shared.llm import get_llm_router
from tools.email import EmailTool

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
    lifespan=lifespan
)

llm_router = get_llm_router()
email_tool = EmailTool()

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

@app.post("/execute")
async def execute_task(
    instruction: str = Body(..., description="Email drafting instruction"),
    recipient: str = Body(..., description="Target email recipient"),
    tone: str = Body("formal", description="Composition tone: formal, short_summary, executive_summary, non_technical"),
    context_data: Optional[Dict[str, Any]] = Body(None, description="System incident metrics, logs, etc.")
):
    """
    Execute high-level email composition task.
    Drafts the email via LLM and sends it using EmailTool.
    """
    logger.info(f"Email Agent received task: {instruction} (Tone: {tone})")
    
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
                {"role": "user", "content": prompt}
            ],
            task="summarize"  # Cheap & fast cost routing
        )
        
        # Clean response string if LLM returned markdown blocks
        clean_str = response_str.strip()
        if clean_str.startswith("```json"):
            clean_str = clean_str[7:]
        if clean_str.endswith("```"):
            clean_str = clean_str[:-3]
        clean_str = clean_str.strip()

        # Parse JSON output from LLM safely
        import json
        try:
            email_data = json.loads(clean_str)
            subject = email_data.get("subject", "AIOps Platform Notification")
            body = email_data.get("body", "No content generated.")
        except Exception as json_err:
            logger.warning(f"Failed to parse LLM response as JSON: {json_err}. Using fallback parsing.")
            # Fallback parsing in case JSON is malformed
            subject = f"AIOps Alert: {instruction[:50]}..."
            body = response_str

        # Send/Save the composed email
        send_result = email_tool.send_email(
            to_address=recipient,
            subject=subject,
            body=body,
            is_html=True
        )

        return {
            "success": True,
            "agent": "email_agent",
            "subject": subject,
            "composed_body": body,
            "send_result": send_result
        }

    except Exception as e:
        logger.error(f"Error executing Email Agent task: {e}")
        raise HTTPException(status_code=500, detail=str(e))
