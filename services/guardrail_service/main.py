"""
Guardrail Service - Enterprise safety layer for AIOps platform engineering.
Performs real-time input sanitization (Prompt Injection) and blocks dangerous tool executions
or routes them to human-in-the-loop approvals based on risk profiles.
"""

import logging
import re
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Body, HTTPException
from contextlib import asynccontextmanager

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
    lifespan=lifespan
)

# Dangerous patterns commonly used in Prompt Injections
PROMPT_INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"override system prompt",
    r"you are now a helpful assistant",
    r"bypass safety",
    r"execute arbitrary",
    r"sudo ",
    r"rm -rf"
]

# Restricted actions requiring Human-in-the-Loop Approval (Medium Risk)
APPROVAL_REQUIRED_ACTIONS = [
    "delete_pod",
    "restart_service",
    "scale_down",
    "apply_yaml",
    "send_incident_report"
]

# Blocked actions (High Risk / Restricted)
CRITICAL_BLOCKED_ACTIONS = [
    "delete_namespace",
    "drop_database",
    "uninstall_helm",
    "purge_logs",
    "execute_shell"
]

@app.get("/health")
def health():
    return {
        "status": "active",
        "service": "guardrail_service",
        "protection_modes": ["input_injection_check", "tool_execution_guard"]
    }

# ──── Input Guardrail (Prompt Injection Protection) ────

@app.post("/guard/input")
def guard_input(prompt: str = Body(..., embed=True)):
    """
    Scans user prompt for injection attempts and malicious instructions.
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

    if triggered_rules:
        logger.warning(f"⚠️ Input Guardrail blocked prompt: {triggered_rules}")
        return {
            "safe": False,
            "action": "block",
            "reason": "Security violation detected: Input contains restricted instruction bypass patterns.",
            "risk_score": 0.95,
            "rules_triggered": triggered_rules
        }

    return {
        "safe": True,
        "action": "allow",
        "risk_score": 0.02,
        "rules_triggered": []
    }

# ──── Tool Guardrail (Human-in-the-Loop & Safety check) ────

@app.post("/guard/tool")
def guard_tool(
    tool_name: str = Body(..., embed=True),
    action: str = Body(..., embed=True),
    parameters: Optional[Dict[str, Any]] = Body(None, embed=True)
):
    """
    Inspects proposed tool executions to prevent destructive operations.
    Categorizes operations into:
    - ALLOW: Safe read-only tasks.
    - APPROVAL: Structural changes requiring manual confirmation.
    - BLOCK: Catastrophic actions completely prohibited.
    """
    logger.info(f"Tool Guardrail inspecting: {tool_name} -> {action}")
    action_key = action.lower()

    # 1. Check critical blocked actions list
    if any(blocked in action_key for blocked in CRITICAL_BLOCKED_ACTIONS):
        logger.warning(f"🚫 Critical block triggered for tool action: {action}")
        return {
            "verdict": "BLOCK",
            "allowed": False,
            "requires_approval": False,
            "reason": f"Action '{action}' is permanently restricted due to extreme system infrastructure risk."
        }

    # 2. Check actions requiring human-in-the-loop approval
    if any(req in action_key for req in APPROVAL_REQUIRED_ACTIONS):
        logger.info(f"🔑 Approval workflow triggered for tool action: {action}")
        return {
            "verdict": "REQUIRE_APPROVAL",
            "allowed": False,
            "requires_approval": True,
            "reason": f"Action '{action}' has structural effects and requires manual operator approval via gateway."
        }

    # 3. Read-only / safe actions default to allow
    return {
        "verdict": "ALLOW",
        "allowed": True,
        "requires_approval": False,
        "reason": f"Action '{action}' evaluated as safe for autonomous execution."
    }
