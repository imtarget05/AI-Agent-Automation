"""DevOps agent for infrastructure analysis and structured remediation proposals."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.config import get_settings
from shared.llm import get_llm_router
from shared.internal_auth import add_internal_auth_middleware
from shared.observability.logging import get_logger
from shared.observability.tracing import start_span

app = FastAPI(title="DevOps Agent")
add_internal_auth_middleware(app)
logger = get_logger(__name__)
settings = get_settings()
llm_router = get_llm_router()

K8S_NAME_PATTERN = r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$"
K8sWriteAction = Literal["restart_deployment", "scale_deployment", "delete_pod"]


class RemediationParameters(BaseModel):
    """Strict parameters accepted by the gateway self-healing workflow."""

    model_config = ConfigDict(extra="forbid")

    namespace: str = Field(
        default="default", min_length=1, max_length=253, pattern=K8S_NAME_PATTERN
    )
    deployment: Optional[str] = Field(
        default=None, min_length=1, max_length=253, pattern=K8S_NAME_PATTERN
    )
    pod: Optional[str] = Field(
        default=None, min_length=1, max_length=253, pattern=K8S_NAME_PATTERN
    )
    replicas: Optional[int] = Field(default=None, ge=0)


class TaskRequest(BaseModel):
    """Analysis request with an optional allow-listed remediation proposal."""

    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1)
    context: Dict[str, Any] = Field(default_factory=dict)
    action: Optional[K8sWriteAction] = None
    parameters: Optional[RemediationParameters] = None

    @model_validator(mode="after")
    def validate_remediation(self) -> "TaskRequest":
        if self.action is None:
            if self.parameters is not None:
                raise ValueError("parameters require a remediation action")
            return self

        if self.parameters is None:
            raise ValueError("remediation action requires parameters")

        required_fields = {
            "restart_deployment": {"deployment"},
            "scale_deployment": {"deployment", "replicas"},
            "delete_pod": {"pod"},
        }[self.action]
        provided_fields = {
            field_name
            for field_name in ("deployment", "pod", "replicas")
            if getattr(self.parameters, field_name) is not None
        }
        if provided_fields != required_fields:
            expected = ", ".join(sorted(required_fields))
            raise ValueError(
                f"{self.action} requires exactly these parameters: {expected}"
            )
        return self


@app.post("/execute")
async def execute_task(req: TaskRequest):
    """Analyze a task or return a proposal for the gateway approval workflow."""
    logger.info("DevOps Agent received task: %s", req.instruction)

    if req.action is None:
        return await _analyze_task(req)

    parameters = _self_healing_parameters(req.action, req.parameters)
    proposed_action = {
        "action": req.action,
        "parameters": parameters,
    }
    return {
        "success": True,
        "message": "DevOps remediation proposal created. Submit it to the gateway approval workflow before execution.",
        "data": {
            "suggestion": _proposal_for(req.action, parameters),
            "proposed_action": proposed_action,
            "approval_endpoint": "/self-healing/approvals",
            "requires_approval": True,
            "applied": False,
        },
    }


async def _analyze_task(req: TaskRequest) -> Dict[str, Any]:
    """Use the LLM for analysis only; LLM output is never executed."""
    try:
        workflow_id = str(req.context.get("workflow_id", ""))
        session_id = str(req.context.get("session_id", ""))
        prompt = f"""You are a DevOps and Platform Engineer.
Analyze the following request and suggest a fix or configuration change.
Instruction: {req.instruction}
Context: {req.context}

Provide a detailed technical suggestion, including YAML or Dockerfile snippets if relevant.
Do not claim that a live change was applied. Kubernetes writes must be returned as an
explicit structured proposal and approved through the gateway self-healing workflow.
"""
        with start_span(
            "devops.analysis",
            {
                "workflow_id": workflow_id,
                "session_id": session_id,
                "agent_name": "devops_agent",
            },
        ):
            chat_kwargs: dict[str, Any] = {}
            if workflow_id or session_id:
                chat_kwargs.update(
                    workflow_id=workflow_id,
                    session_id=session_id,
                    agent_name="devops_agent",
                    estimated_tokens=1800,
                )
            suggestion = await llm_router.chat(
                [{"role": "user", "content": prompt}],
                task="code",
                **chat_kwargs,
            )
        return {
            "success": True,
            "message": "DevOps analysis completed.",
            "data": {
                "suggestion": suggestion,
                "applied": False,
            },
        }
    except Exception as exc:
        logger.error("DevOps analysis failed: %s", exc)
        return {"success": False, "error": str(exc)}


def _self_healing_parameters(
    action: K8sWriteAction,
    parameters: RemediationParameters,
) -> Dict[str, Any]:
    """Build payload parameters compatible with Gateway and ToolService."""
    if action == "restart_deployment":
        return {
            "namespace": parameters.namespace,
            "deployment": parameters.deployment,
        }
    if action == "scale_deployment":
        return {
            "namespace": parameters.namespace,
            "deployment": parameters.deployment,
            "replicas": parameters.replicas,
        }
    return {
        "namespace": parameters.namespace,
        "pod": parameters.pod,
    }


def _proposal_for(action: K8sWriteAction, parameters: Dict[str, Any]) -> str:
    """Return a deterministic human-readable remediation proposal."""
    namespace = parameters["namespace"]
    if action == "restart_deployment":
        return (
            f"Propose a rolling restart of deployment '{parameters['deployment']}' "
            f"in namespace '{namespace}'."
        )
    if action == "scale_deployment":
        return (
            f"Propose scaling deployment '{parameters['deployment']}' to "
            f"{parameters['replicas']} replicas in namespace '{namespace}'."
        )
    return f"Propose deleting pod '{parameters['pod']}' in namespace '{namespace}'."


@app.get("/health")
async def health():
    return {"status": "ok"}
