"""
Guardrail Service - Enterprise safety layer for AIOps platform engineering.
Performs real-time input sanitization (Prompt Injection) and blocks dangerous tool executions
or routes them to human-in-the-loop approvals based on risk profiles.
"""

import logging
import re
from datetime import datetime
from typing import Dict, Any, Optional
from shared.config import get_bind_host
from uuid import uuid4
from fastapi import FastAPI, Body, HTTPException
from contextlib import asynccontextmanager
from shared.internal_auth import add_internal_auth_middleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("guardrail_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🛡️ Starting AIOps Guardrail microservice")
    yield
    logger.info("🛑 Shutting down Guardrail service")


app = FastAPI(
    title="AIOps Enterprise Guardrail",
    description="Safety middleware protecting platform infrastructure from unsafe LLM actions and injections",
    version="1.0.0",
    lifespan=lifespan,
)
add_internal_auth_middleware(app)

# Dangerous patterns commonly used in Prompt Injections
PROMPT_INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"override system prompt",
    r"you are now a helpful assistant",
    r"bypass safety",
    r"execute arbitrary",
    r"sudo ",
    r"rm -rf",
]


class PIIAnonymizer:
    """
    Enterprise PII & Secret Anonymization Layer.
    Detects and masks sensitive business/infrastructure data before forwarding to Cloud LLMs.
    """

    # Regex patterns for high-sensitivity data
    IP_PATTERN = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    IPV6_PATTERN = r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"
    EMAIL_PATTERN = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    SSH_KEY_PATTERN = (
        r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+ PRIVATE KEY-----"
    )

    # Matches api keys, bearer tokens, connection strings, webhooks
    SECRET_PATTERN = r"(?i)(?:bearer\s+[a-zA-Z0-9_\-\.]+)|(?:api[_-]?key|secret|token|password|password_hash|client[_-]?secret)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-\.\/]{12,}['\"]?"
    SLACK_WEBHOOK_PATTERN = (
        r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"
    )

    def __init__(self):
        self.ip_mapping: Dict[str, str] = {}
        self.secret_mapping: Dict[str, str] = {}
        self.email_mapping: Dict[str, str] = {}

    def anonymize(self, text: str) -> tuple[str, Dict[str, Any]]:
        """
        Anonymizes PII in text and returns the masked text and the translation mapping.
        """
        masked = text
        mapping = {}

        # 1. Anonymize SSH Keys
        ssh_matches = re.findall(self.SSH_KEY_PATTERN, masked)
        for i, match in enumerate(ssh_matches):
            placeholder = f"[ANONYMIZED_SSH_PRIVATE_KEY_{i + 1}]"
            masked = masked.replace(match, placeholder)
            mapping[placeholder] = match

        # 2. Anonymize Slack Webhooks
        webhook_matches = re.findall(self.SLACK_WEBHOOK_PATTERN, masked)
        for i, match in enumerate(webhook_matches):
            placeholder = f"[ANONYMIZED_SLACK_WEBHOOK_{i + 1}]"
            masked = masked.replace(match, placeholder)
            mapping[placeholder] = match

        # 3. Anonymize Secrets & API Keys
        secret_matches = re.findall(self.SECRET_PATTERN, masked)
        for i, match in enumerate(secret_matches):
            placeholder = f"[ANONYMIZED_SECRET_{i + 1}]"
            masked = masked.replace(match, placeholder)
            mapping[placeholder] = match

        # 4. Anonymize IP Addresses
        ip_matches = set(re.findall(self.IP_PATTERN, masked))
        local_hosts = {get_bind_host(), "127.0.0.1"}
        for i, match in enumerate(ip_matches):
            # Ignore localhost or the configured bind host; mask others for safety
            if match not in local_hosts:
                placeholder = f"[ANONYMIZED_IP_{i + 1}]"
                masked = re.sub(re.escape(match), placeholder, masked)
                mapping[placeholder] = match

        # 5. Anonymize IPv6 Addresses
        ipv6_matches = set(re.findall(self.IPV6_PATTERN, masked))
        for i, match in enumerate(ipv6_matches):
            placeholder = f"[ANONYMIZED_IPV6_{i + 1}]"
            masked = re.sub(re.escape(match), placeholder, masked)
            mapping[placeholder] = match

        # 6. Anonymize Emails
        email_matches = set(re.findall(self.EMAIL_PATTERN, masked))
        for i, match in enumerate(email_matches):
            placeholder = f"[ANONYMIZED_EMAIL_{i + 1}]"
            masked = re.sub(re.escape(match), placeholder, masked)
            mapping[placeholder] = match

        return masked, mapping


anonymizer = PIIAnonymizer()

# Restricted actions requiring Human-in-the-Loop Approval (Medium Risk)
APPROVAL_REQUIRED_ACTIONS = [
    "delete_pod",
    "restart_deployment",
    "restart_service",
    "scale_deployment",
    "scale_down",
    "apply_yaml",
    "send_incident_report",
]

# Blocked actions (High Risk / Restricted)
CRITICAL_BLOCKED_ACTIONS = [
    "delete_namespace",
    "drop_database",
    "uninstall_helm",
    "purge_logs",
    "execute_shell",
]

approval_requests: Dict[str, Dict[str, Any]] = {}


@app.get("/health")
def health():
    return {
        "status": "active",
        "service": "guardrail_service",
        "protection_modes": [
            "input_injection_check",
            "tool_execution_guard",
            "pii_anonymization",
        ],
    }


# ──── Input Guardrail (Prompt Injection & PII Masking) ────


@app.post("/guard/input")
def guard_input(prompt: str = Body(..., embed=True)):
    """
    Scans user prompt for injection attempts and anonymizes PII/Sensitive data.
    """
    logger.info(f"Input Guardrail scanning prompt of length: {len(prompt)}")

    triggered_rules = []

    # 1. Match against known injection patterns
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, prompt, re.IGNORECASE):
            triggered_rules.append(f"Prompt injection pattern match: '{pattern}'")

    # 2. Check for suspicious length or repetition indicating bypass tries
    if len(prompt) > 5000:
        triggered_rules.append("Prompt size exceeds safe evaluation limit (5000 chars)")

    # 3. Perform PII Masking / Anonymization
    anonymized_prompt, mapping = anonymizer.anonymize(prompt)
    pii_detected = len(mapping) > 0
    if pii_detected:
        logger.info(
            f"🔒 PII Anonymization Layer masked {len(mapping)} sensitive entities."
        )

    if triggered_rules:
        logger.warning(f"⚠️ Input Guardrail blocked prompt: {triggered_rules}")
        return {
            "safe": False,
            "action": "block",
            "reason": "Security violation detected: Input contains restricted instruction bypass patterns.",
            "risk_score": 0.95,
            "rules_triggered": triggered_rules,
            "anonymized_prompt": anonymized_prompt,
            "pii_detected": pii_detected,
        }

    return {
        "safe": True,
        "action": "allow",
        "risk_score": 0.02,
        "rules_triggered": [],
        "anonymized_prompt": anonymized_prompt,
        "pii_detected": pii_detected,
        "entities_masked_count": len(mapping),
    }


@app.post("/guard/anonymize")
def guard_anonymize(text: str = Body(..., embed=True)):
    """
    Utility endpoint to mask sensitive info (IP, emails, secrets) in logs or code.
    """
    anonymized, mapping = anonymizer.anonymize(text)
    return {
        "anonymized_text": anonymized,
        "entities_masked_count": len(mapping),
    }


# ──── Tool Guardrail (Human-in-the-Loop & Safety check) ────


def _evaluate_tool(
    tool_name: str,
    action: str,
    parameters: Optional[Dict[str, Any]] = None,
    approval_id: Optional[str] = None,
):
    """Classify a tool action and honor matching operator approvals."""
    logger.info(f"Tool Guardrail inspecting: {tool_name} -> {action}")
    action_key = action.lower()
    parameters = parameters or {}

    if any(blocked in action_key for blocked in CRITICAL_BLOCKED_ACTIONS):
        logger.warning(f"🚫 Critical block triggered for tool action: {action}")
        return {
            "verdict": "BLOCK",
            "allowed": False,
            "requires_approval": False,
            "reason": f"Action '{action}' is permanently restricted due to extreme system infrastructure risk.",
        }

    if any(req in action_key for req in APPROVAL_REQUIRED_ACTIONS):
        approval = approval_requests.get(approval_id or "")
        if approval:
            if (
                approval["tool_name"] != tool_name
                or approval["action"] != action
                or approval["parameters"] != parameters
            ):
                return {
                    "verdict": "BLOCK",
                    "allowed": False,
                    "requires_approval": False,
                    "reason": "Approval does not match the requested tool action and parameters.",
                }
            if approval["status"] == "approved":
                return {
                    "verdict": "ALLOW",
                    "allowed": True,
                    "requires_approval": False,
                    "approval_id": approval_id,
                    "reason": f"Action '{action}' was approved by {approval['decided_by']}.",
                }
            if approval["status"] == "rejected":
                return {
                    "verdict": "BLOCK",
                    "allowed": False,
                    "requires_approval": False,
                    "approval_id": approval_id,
                    "reason": f"Action '{action}' was rejected by {approval['decided_by']}.",
                }

        logger.info(f"🔑 Approval workflow triggered for tool action: {action}")
        return {
            "verdict": "REQUIRE_APPROVAL",
            "allowed": False,
            "requires_approval": True,
            "approval_id": approval_id,
            "reason": f"Action '{action}' has structural effects and requires manual operator approval via gateway.",
        }

    return {
        "verdict": "ALLOW",
        "allowed": True,
        "requires_approval": False,
        "reason": f"Action '{action}' evaluated as safe for autonomous execution.",
    }


@app.post("/guard/tool")
def guard_tool(
    tool_name: str = Body(..., embed=True),
    action: str = Body(..., embed=True),
    parameters: Optional[Dict[str, Any]] = Body(None, embed=True),
    approval_id: Optional[str] = Body(None, embed=True),
):
    """Evaluate whether a tool action is allowed to execute."""
    return _evaluate_tool(tool_name, action, parameters, approval_id)


@app.post("/approvals")
def create_approval_request(
    tool_name: str = Body(..., embed=True),
    action: str = Body(..., embed=True),
    parameters: Optional[Dict[str, Any]] = Body(None, embed=True),
):
    """Create a pending operator approval for a guarded tool action."""
    parameters = parameters or {}
    verdict = _evaluate_tool(tool_name, action, parameters)
    if verdict["verdict"] == "BLOCK":
        raise HTTPException(status_code=403, detail=verdict["reason"])
    if not verdict["requires_approval"]:
        return {
            "requires_approval": False,
            "verdict": verdict,
        }

    approval_id = str(uuid4())
    approval = {
        "approval_id": approval_id,
        "tool_name": tool_name,
        "action": action,
        "parameters": parameters,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "decided_at": None,
        "decided_by": None,
    }
    approval_requests[approval_id] = approval
    return {
        "requires_approval": True,
        "approval": approval,
    }


@app.get("/approvals/{approval_id}")
def get_approval_request(approval_id: str):
    """Return the current approval state."""
    approval = approval_requests.get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return approval


@app.post("/approvals/{approval_id}/decision")
def decide_approval_request(
    approval_id: str,
    approved: bool = Body(..., embed=True),
    decided_by: str = Body(..., embed=True),
):
    """Record a one-time operator decision for a pending action."""
    approval = approval_requests.get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval["status"] != "pending":
        raise HTTPException(
            status_code=409, detail="Approval request was already decided"
        )

    approval["status"] = "approved" if approved else "rejected"
    approval["decided_at"] = datetime.utcnow().isoformat()
    approval["decided_by"] = decided_by
    return approval
