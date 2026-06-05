"""
Tool Registry Service - FastAPI entry point exposing REST endpoints for local tools.
Allows other services (Gateway, n8n, etc.) to trigger K8s, Prometheus, and Email tools via HTTP.
"""

import hashlib
import logging
from typing import Any, Literal, Optional
from fastapi import FastAPI, Query, Body, HTTPException
from pydantic import BaseModel, Field

from tools.k8s import K8sTool
from tools.prometheus import PrometheusTool
from tools.email import EmailTool
from tools.github import GitHubTool
from tools.slack import SlackTool
from shared.approvals import ApprovalClient, ApprovalServiceError
from shared.guardrails import GuardrailClient, GuardrailServiceError
from shared.internal_auth import add_internal_auth_middleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tool_service")

app = FastAPI(
    title="Multi-Agent AIOps Tool Registry",
    description="REST API service hosting platform execution tools for agents",
    version="1.0.0",
)
add_internal_auth_middleware(app)

# Initialize tool clients
k8s_tool = K8sTool()
prometheus_tool = PrometheusTool()
email_tool = EmailTool()
github_tool = GitHubTool()
slack_tool = SlackTool()
guardrail_client = GuardrailClient()
approval_client = ApprovalClient()


class ToolTaskRequest(BaseModel):
    """Natural-language request routed from the orchestration layer."""

    instruction: str


class K8sWriteActionRequest(BaseModel):
    """Approved Kubernetes mutation dispatched by the Gateway callback."""

    action: Literal["restart_deployment", "scale_deployment", "delete_pod"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    approval_id: str


@app.get("/health")
def health_check():
    """Service health state"""
    return {
        "status": "healthy",
        "real_k8s_connected": k8s_tool.use_real_k8s,
        "tools_registered": ["k8s", "prometheus", "email", "github", "slack"],
    }


@app.post("/execute")
async def execute_tool_task(request: ToolTaskRequest):
    """Dispatch read-only infrastructure queries from the orchestrator."""
    instruction = request.instruction.lower()
    write_keywords = (
        "apply",
        "cordon",
        "delete",
        "drain",
        "exec",
        "patch",
        "restart",
        "rollout",
        "scale",
    )
    if any(keyword in instruction for keyword in write_keywords):
        return {
            "success": False,
            "error": "Tool dispatcher rejected a state-changing request. Only read-only queries are supported.",
        }
    if "event" in instruction:
        return {"success": True, "events": k8s_tool.get_events()}
    if "pod" in instruction:
        return {"success": True, "pods": k8s_tool.get_pods()}
    if any(
        keyword in instruction
        for keyword in ("cpu", "memory", "latency", "prometheus", "promql")
    ):
        result = await prometheus_tool.query_metric(request.instruction)
        return {"success": True, "metrics": result}
    return {
        "success": False,
        "error": "Tool dispatcher only supports read-only pod, event, and Prometheus queries.",
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
    tail_lines: int = Query(50, description="Log lines to read"),
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
    pod_name: str, namespace: str = Query("default", description="K8s Namespace")
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


@app.post("/k8s/actions/execute")
async def execute_k8s_write_action(request: K8sWriteActionRequest):
    """Execute an approved write action after a final policy re-check."""
    try:
        approval = await approval_client.get_approval(request.approval_id)
        if approval.get("status") != "approved":
            raise HTTPException(status_code=409, detail="Operator approval is required")
        if approval.get("action") != request.action:
            raise HTTPException(
                status_code=409, detail="Approval action does not match callback"
            )
        if (approval.get("parameters") or {}) != request.parameters:
            raise HTTPException(
                status_code=409, detail="Approval parameters do not match callback"
            )

        verdict = await guardrail_client.guard_tool(
            tool_name="k8s",
            action=request.action,
            parameters=request.parameters,
        )
        if verdict.get("verdict") == "BLOCK":
            raise HTTPException(
                status_code=403,
                detail=verdict.get("reason", "Kubernetes action blocked by guardrail"),
            )
        await approval_client.claim_execution(request.approval_id)

        namespace = request.parameters.get("namespace", "default")
        if request.action == "restart_deployment":
            result = k8s_tool.restart_deployment(
                deployment_name=request.parameters["deployment"],
                namespace=namespace,
            )
        elif request.action == "scale_deployment":
            result = k8s_tool.scale_deployment(
                deployment_name=request.parameters["deployment"],
                replicas=int(request.parameters["replicas"]),
                namespace=namespace,
            )
        else:
            result = k8s_tool.delete_pod(
                pod_name=request.parameters["pod"],
                namespace=namespace,
            )

        return {
            "success": True,
            "approval_id": request.approval_id,
            "action": request.action,
            "result": result,
        }
    except KeyError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Missing action parameter: {exc.args[0]}",
        ) from exc
    except (ApprovalServiceError, GuardrailServiceError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/prometheus/query")
async def query_prometheus(
    query: str = Query(..., description="PromQL statement"),
    time: Optional[str] = Query(None, description="Target evaluation timestamp"),
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
            to_address=to_address, subject=subject, body=body, is_html=is_html
        )
        return result
    except GuardrailServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---- GitHub API endpoints ----


@app.post("/github/issue")
async def create_github_issue(
    repo: str = Body(..., embed=True),
    title: str = Body(..., embed=True),
    body: str = Body(..., embed=True),
):
    """Create a new GitHub issue"""
    try:
        return await github_tool.create_issue(repo, title, body)
    except Exception as e:
        logger.error(f"GitHub Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/github/comment")
async def create_github_comment(
    repo: str = Body(..., embed=True),
    pr_number: int = Body(..., embed=True),
    body: str = Body(..., embed=True),
):
    """Comment on a Pull Request"""
    try:
        return await github_tool.create_pr_comment(repo, pr_number, body)
    except Exception as e:
        logger.error(f"GitHub Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──── Slack API endpoints ────


@app.post("/slack/post")
async def post_slack_message(
    channel: str = Body(..., embed=True), text: str = Body(..., embed=True)
):
    """Post message to Slack channel"""
    try:
        return await slack_tool.post_message(channel, text)
    except Exception as e:
        logger.error(f"Slack Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
