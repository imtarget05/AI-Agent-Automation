"""
Tool Registry Service - FastAPI entry point exposing REST endpoints for local tools.
Allows other services (Gateway, n8n, etc.) to trigger K8s, Prometheus, and Email tools via HTTP.
"""

import logging
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Query, Body, HTTPException

from tools.k8s import K8sTool
from tools.prometheus import PrometheusTool
from tools.email import EmailTool

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

@app.get("/health")
def health_check():
    """Service health state"""
    return {
        "status": "healthy",
        "real_k8s_connected": k8s_tool.use_real_k8s,
        "tools_registered": ["k8s", "prometheus", "email"]
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
def send_email(
    to_address: str = Body(..., embed=True),
    subject: str = Body(..., embed=True),
    body: str = Body(..., embed=True),
    is_html: bool = Body(False, embed=True)
):
    """Draft or transmit standard stakeholder/alert email"""
    try:
        result = email_tool.send_email(
            to_address=to_address,
            subject=subject,
            body=body,
            is_html=is_html
        )
        return result
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        raise HTTPException(status_code=500, detail=str(e))
