"""Agent execution application service for the Gateway."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

import httpx

from shared.approvals import ApprovalClient
from shared.config import Settings
from shared.guardrails import GuardrailClient
from shared.models import ModuleType, Task, TaskResult, TaskStatus

logger = logging.getLogger(__name__)


class LlmClient(Protocol):
    """Minimal LLM port required for critical-action reflection."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        task: str,
        temperature: float = 0.7,
    ) -> str: ...


class ApprovalGateway(Protocol):
    """Approval port used when a critical action needs operator review."""

    async def create_approval(
        self,
        task_id: str,
        agent: str,
        action: str,
        parameters: Optional[dict] = None,
        reason: Optional[str] = None,
    ) -> dict: ...


class GuardrailGateway(Protocol):
    """Safety policy port for prompt and tool checks."""

    async def guard_input(self, prompt: str) -> dict[str, Any]: ...

    async def guard_tool(
        self,
        tool_name: str,
        action: str,
        parameters: Optional[dict[str, Any]] = None,
        approval_id: Optional[str] = None,
    ) -> dict[str, Any]: ...


class AgentGateway(Protocol):
    """Transport port for invoking a remote agent."""

    async def post_json(
        self,
        base_url: str,
        path: str,
        payload: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]: ...


class HttpAgentGateway:
    """HTTP adapter for remote agent services."""

    async def post_json(
        self,
        base_url: str,
        path: str,
        payload: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, dict):
            raise ValueError("Agent service returned a non-object response")
        return data


@dataclass(frozen=True)
class AgentSpec:
    """Configuration and payload mapping for a remote agent boundary."""

    settings_attr: str
    path: str = "/execute"
    payload_builder: Callable[[Task], dict[str, Any]] = lambda task: {
        "instruction": task.instruction
    }

    def build_payload(self, task: Task) -> dict[str, Any]:
        return self.payload_builder(task)


REMOTE_AGENT_SPECS: dict[ModuleType, AgentSpec] = {
    ModuleType.COMPUTER_USE: AgentSpec(
        "computer_use_service_url",
        payload_builder=lambda task: {"objective": task.instruction},
    ),
    ModuleType.BROWSER: AgentSpec(
        "browser_service_url",
        payload_builder=lambda task: _build_browser_payload(task),
    ),
    ModuleType.RAG: AgentSpec(
        "rag_service_url",
        path="/retrieve",
        payload_builder=lambda task: {"query": task.instruction, "top_k": 5},
    ),
    ModuleType.EMAIL: AgentSpec(
        "email_agent_service_url",
        payload_builder=lambda task: _build_email_payload(task),
    ),
    ModuleType.TOOL: AgentSpec("tool_service_url"),
    ModuleType.GUARDRAIL: AgentSpec(
        "guardrail_service_url",
        path="/guard/tool",
        payload_builder=lambda task: {
            "tool_name": "unknown",
            "action": task.instruction,
            "parameters": {},
        },
    ),
    ModuleType.AIOPS: AgentSpec("aiops_agent_service_url"),
    ModuleType.RCA: AgentSpec("rca_agent_service_url"),
    ModuleType.DEVOPS: AgentSpec("devops_agent_service_url"),
    ModuleType.REPORT: AgentSpec("report_agent_service_url"),
}

CRITICAL_ACTION_AGENTS = frozenset(
    {ModuleType.TOOL, ModuleType.COMPUTER_USE, ModuleType.DEVOPS}
)
LOCAL_BLOCK_PATTERNS = (
    r"ignore previous",
    r"override system",
    r"rm -rf",
    r"sudo ",
)


class AgentExecutionService:
    """Run one planned task behind explicit infrastructure ports."""

    def __init__(
        self,
        settings: Settings,
        llm: LlmClient,
        approvals: Optional[ApprovalGateway] = None,
        guardrails: Optional[GuardrailGateway] = None,
        agents: Optional[AgentGateway] = None,
    ):
        self.settings = settings
        self.llm = llm
        self.approvals = approvals or ApprovalClient(settings.approval_service_url)
        self.guardrails = guardrails or GuardrailClient(settings.guardrail_service_url)
        self.agents = agents or HttpAgentGateway()

    async def execute(self, task: Task, approved: bool = False) -> TaskResult:
        """Run a task after safety checks and return a stable domain result."""
        started_at = time.perf_counter()
        payload = REMOTE_AGENT_SPECS[task.agent].build_payload(task)

        risk_reason = await self._find_input_risk(task.instruction)
        if risk_reason:
            logger.warning(
                "[GUARDRAIL BLOCK] Input blocked for task %s: %s",
                task.id,
                risk_reason,
            )
            return self._result(
                task,
                TaskStatus.FAILED,
                started_at,
                error_message=f"Input safety block: {risk_reason}",
            )

        if task.agent in CRITICAL_ACTION_AGENTS:
            blocked_result = await self._check_critical_action(
                task=task,
                payload=payload,
                started_at=started_at,
                approved=approved,
            )
            if blocked_result:
                return blocked_result

        spec = REMOTE_AGENT_SPECS[task.agent]
        base_url = getattr(self.settings, spec.settings_attr)
        try:
            response = await self.agents.post_json(
                base_url=base_url,
                path=spec.path,
                payload=payload,
                timeout=task.timeout_seconds
                or self.settings.agent_http_timeout_seconds,
            )
            await self._reflect_on_failure(task, response)
            status = (
                TaskStatus.COMPLETED
                if response.get("success", True)
                else TaskStatus.FAILED
            )
            return self._result(
                task,
                status,
                started_at,
                output=response,
                error_message=response.get("error"),
            )
        except Exception as exc:
            logger.error(
                "[%s] Task %s failed: %s", task.agent.value.upper(), task.id, exc
            )
            return self._result(
                task,
                TaskStatus.FAILED,
                started_at,
                error_message=str(exc),
            )

    async def _find_input_risk(self, instruction: str) -> Optional[str]:
        try:
            verdict = await self.guardrails.guard_input(instruction)
            if not verdict.get("safe", True):
                return verdict.get("reason", "Malicious input pattern detected.")
            return None
        except Exception as exc:
            logger.warning(
                "Could not reach guardrail service: %s. Running local pattern scanner fallback.",
                exc,
            )

        for pattern in LOCAL_BLOCK_PATTERNS:
            if re.search(pattern, instruction, re.IGNORECASE):
                return f"Local safety scanner matched pattern: '{pattern}'"
        return None

    async def _check_critical_action(
        self,
        task: Task,
        payload: dict[str, Any],
        started_at: float,
        approved: bool,
    ) -> Optional[TaskResult]:
        try:
            verdict = await self.guardrails.guard_tool(
                tool_name=task.agent.value,
                action=task.instruction,
                parameters=payload,
            )
        except Exception as exc:
            return self._result(
                task,
                TaskStatus.FAILED,
                started_at,
                error_message=f"Guardrail service unavailable: {exc}",
            )

        if verdict.get("verdict") == "BLOCK":
            return self._result(
                task,
                TaskStatus.FAILED,
                started_at,
                output=verdict,
                error_message=verdict.get(
                    "reason",
                    "Tool action blocked by guardrail",
                ),
            )

        if verdict.get("requires_approval") and not approved:
            try:
                approval = await self.approvals.create_approval(
                    task_id=task.id,
                    agent=task.agent.value,
                    action=task.instruction,
                    parameters=payload,
                    reason=verdict.get("reason"),
                )
            except Exception as exc:
                approval = {"error": f"Approval service unavailable: {exc}"}

            return self._result(
                task,
                TaskStatus.FAILED,
                started_at,
                output={"status": "AWAITING_APPROVAL", "approval": approval},
                error_message="Tool action requires operator approval.",
            )

        return None

    async def _reflect_on_failure(
        self,
        task: Task,
        response: dict[str, Any],
    ) -> None:
        if task.agent not in CRITICAL_ACTION_AGENTS:
            return
        if (
            response.get("success", True)
            and "error" not in response
            and response.get("status") != "failed"
        ):
            return

        prompt = f"""You are a Senior Site Reliability Engineer.
Critique the following DevOps command or action execution result.
Task Objective: {task.instruction}
Execution Output: {response}

Analyze if there are syntax errors, invalid parameters, potential system damage,
or logical failures. If there are errors, describe them clearly and specify how
to correct them. If everything is correct, safe, and complete, reply only with
'APPROVED'."""
        try:
            critique = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                task="planning",
                temperature=0.2,
            )
        except Exception as exc:
            logger.error("[SELF-REFLECTION] Failed to execute critique: %s", exc)
            return

        if "APPROVED" not in critique:
            response["self_reflection_applied"] = True
            response["critique"] = critique
            response["automatic_retry_blocked"] = True

    @staticmethod
    def _result(
        task: Task,
        status: TaskStatus,
        started_at: float,
        output: object = None,
        error_message: Optional[str] = None,
    ) -> TaskResult:
        return TaskResult(
            task_id=task.id,
            agent=task.agent,
            status=status,
            output=output,
            error_message=error_message,
            execution_time_seconds=time.perf_counter() - started_at,
        )


def _build_email_payload(task: Task) -> dict[str, Any]:
    recipient_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", task.instruction)
    return {
        "instruction": task.instruction,
        "recipient": (
            recipient_match.group(0) if recipient_match else "supervisor@company.com"
        ),
        "mode": "draft",
    }


def _build_browser_payload(task: Task) -> dict[str, Any]:
    payload: dict[str, Any] = {"instruction": task.instruction}

    url = _extract_url(task.instruction)
    if url:
        payload["url"] = url

    extract_fields = _extract_fields(task.expected_output_schema)
    if extract_fields:
        payload["extract_fields"] = extract_fields

    return payload


def _extract_url(text: str) -> Optional[str]:
    url_match = re.search(r"https?://\S+", text)
    if url_match:
        return url_match.group(0)

    domain_match = re.search(r"\b([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/\S*)?\b", text)
    if domain_match:
        return f"https://{domain_match.group(0)}"
    return None


def _extract_fields(schema: Optional[dict]) -> Optional[list[str]]:
    if not schema:
        return None
    fields = schema.get("fields")
    if isinstance(fields, list) and all(isinstance(field, str) for field in fields):
        return fields
    return None
