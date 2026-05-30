"""
Tool Registry Service - FastAPI entry point exposing REST endpoints for local tools.
Allows other services (Gateway, n8n, etc.) to trigger K8s, Prometheus, and Email tools via HTTP.
"""

import hashlib
import logging
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Query, Body, HTTPException

from tools.k8s import K8sTool
from tools.prometheus import PrometheusTool
from tools.email import EmailTool
from tools.github import GitHubTool
from tools.slack import SlackTool
from shared.guardrails import GuardrailClient, GuardrailServiceError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tool_service")

app = FastAPI(
    title="Multi-Agent AIOps Tool Registry",
    description="REST API service hosting platform execution tools for agents",
    version="1.0.0"
)

# Initialize tool clients
k8s_tool = K8sTool()
prometheus_tool = PrometheusTool()
email_tool = EmailTool()
github_tool = GitHubTool()
slack_tool = SlackTool()
guardrail_client = GuardrailClient()

@app.get("/health")
def health_check():
    """Service health state"""
    return {
        "status": "healthy",
        "real_k8s_connected": k8s_tool.use_real_k8s,
        "tools_registered": ["k8s", "prometheus", "email", "github", "slack"]
    }

# ──── Kubernetes API endpoints ────

@app.get("/k8s/pods")
def list_pods(namespace: str = Query("default", description="K8s Namespace")):
    """List pods in namespace with status and restart metrics"""
    try:
        pods = k8s_tool.get_pods(namespace)
        return {"success": True, "pods": pods}
    except Exception as e:
        logger.error(f"Error listing pods: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/k8s/logs")
def get_pod_logs(
    pod_name: str = Query(..., description="Pod identifier"),
    namespace: str = Query("default", description="K8s Namespace"),
    tail_lines: int = Query(50, description="Log lines to read")
):
    """Retrieve stdout/stderr logs for a specific pod"""
    try:
        logs = k8s_tool.get_pod_logs(pod_name, namespace, tail_lines)
        return {"success": True, "pod": pod_name, "logs": logs}
    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/k8s/events")
def list_events(namespace: str = Query("default", description="K8s Namespace")):
    """List cluster events in namespace"""
    try:
        events = k8s_tool.get_events(namespace)
        return {"success": True, "events": events}
    except Exception as e:
        logger.error(f"Error listing events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/k8s/pods/{pod_name}")
def describe_pod(
    pod_name: str,
    namespace: str = Query("default", description="K8s Namespace")
):
    """Retrieve a read-only pod summary for incident analysis"""
    try:
        pod = k8s_tool.describe_pod(pod_name, namespace)
        return {"success": True, "pod": pod}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error describing pod: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ──── Prometheus API endpoints ────

@app.get("/prometheus/query")
async def query_prometheus(
    query: str = Query(..., description="PromQL statement"),
    time: Optional[str] = Query(None, description="Target evaluation timestamp")
):
    """Query Prometheus database metrics"""
    try:
        result = await prometheus_tool.query_metric(query, time)
        return result
    except Exception as e:
        logger.error(f"Error querying Prometheus: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ──── Email API endpoints ────

@app.post("/email/send")
async def send_email(
    to_address: str = Body(..., embed=True),
    subject: str = Body(..., embed=True),
    body: str = Body(..., embed=True),
    is_html: bool = Body(False, embed=True),
    approval_id: Optional[str] = Body(None, embed=True),
):
    """Transmit a stakeholder email only after operator approval."""
    parameters = {
        "to_address": to_address,
        "subject": subject,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "is_html": is_html,
    }

    try:
        verdict = await guardrail_client.guard_tool(
            tool_name="email",
            action="send_incident_report",
            parameters=parameters,
            approval_id=approval_id,
        )
        if verdict.get("requires_approval"):
            if approval_id:
                return {
                    "success": False,
                    **verdict,
                }
            approval = await guardrail_client.request_approval(
                tool_name="email",
                action="send_incident_report",
                parameters=parameters,
            )
            return {
                "success": False,
                "requires_approval": True,
                "approval": approval["approval"],
            }
        if not verdict.get("allowed"):
            raise HTTPException(
                status_code=403,
                detail=verdict.get("reason", "Email send blocked by guardrail service"),
            )

        result = email_tool.send_email(
            to_address=to_address,
            subject=subject,
            body=body,
            is_html=is_html
        )
        return result
    except GuardrailServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    title: str = Body(..., embed=True),
    body: str = Body(..., embed=True)
):
    """Create a new GitHub issue"""
    try:
        return github_tool.create_issue(repo, title, body)
    except Exception as e:
        logger.error(f"GitHub Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/github/comment")
def create_github_comment(
    repo: str = Body(..., embed=True),
    pr_number: int = Body(..., embed=True),
    body: str = Body(..., embed=True)
):
    """Comment on a Pull Request"""
    try:
        return github_tool.create_pr_comment(repo, pr_number, body)
    except Exception as e:
        logger.error(f"GitHub Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ──── Slack API endpoints ────

@app.post("/slack/post")
def post_slack_message(
    channel: str = Body(..., embed=True),
    text: str = Body(..., embed=True)
):
    """Post message to Slack channel"""
    try:
        return slack_tool.post_message(channel, text)
    except Exception as e:
        logger.error(f"Slack Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
