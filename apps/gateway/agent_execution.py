"""Agent execution application service for the Gateway."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

import httpx

from shared.approvals import ApprovalClient
from shared.claw import ClawWrapper
from shared.config import Settings
from shared.guardrails import GuardrailClient
from shared.internal_auth import get_internal_service_headers
from shared.mcp import get_mcp_manager
from shared.models import ModuleType, Task, TaskResult, TaskStatus
from shared.observability.logging import get_logger
from shared.observability.tracing import record_error, start_span

logger = get_logger(__name__)


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
            response = await client.post(
                url,
                json=payload,
                headers=get_internal_service_headers(),
            )
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
        "instruction": task.instruction,
        "context": task.context,
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
        payload_builder=lambda task: _with_context(
            _build_email_payload(task), task, key="context_data"
        ),
    ),
    ModuleType.TOOL: AgentSpec(
        "tool_service_url",
        payload_builder=lambda task: {"instruction": task.instruction},
    ),
    ModuleType.GUARDRAIL: AgentSpec(
        "guardrail_service_url",
        path="/guard/tool",
        payload_builder=lambda task: {
            "tool_name": "unknown",
            "action": task.instruction,
            "parameters": {},
        },
    ),
    ModuleType.AIOPS: AgentSpec(
        "aiops_agent_service_url",
        payload_builder=lambda task: _with_context(
            {"instruction": task.instruction}, task
        ),
    ),
    ModuleType.RCA: AgentSpec(
        "rca_agent_service_url",
        payload_builder=lambda task: _with_context(
            {"instruction": task.instruction}, task
        ),
    ),
    ModuleType.DEVOPS: AgentSpec(
        "devops_agent_service_url",
        payload_builder=lambda task: _with_context(
            {"instruction": task.instruction}, task
        ),
    ),
    ModuleType.REPORT: AgentSpec(
        "report_agent_service_url",
        payload_builder=lambda task: _with_context(
            {"instruction": task.instruction}, task
        ),
    ),
    ModuleType.AGENTSCOPE: AgentSpec(
        "agentscope_agent_service_url",
        payload_builder=lambda task: _with_context(
            {"instruction": task.instruction}, task
        ),
    ),
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
        workflow_id = str(task.context.get("workflow_id", ""))
        session_id = str(task.context.get("session_id", ""))

        with start_span(
            "agent.execute",
            {
                "workflow_id": workflow_id,
                "session_id": session_id,
                "agent_name": task.agent.value,
                "task_id": task.id,
            },
        ) as span:
            risk_reason = await self._find_input_risk(
                task.instruction,
                workflow_id=workflow_id,
                session_id=session_id,
            )
            if risk_reason:
                span.set_attribute("status", "guardrail_blocked")
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

            if task.agent == ModuleType.MCP:
                return await self._execute_mcp(task, started_at, approved)

            if task.agent == ModuleType.CLAW:
                if not getattr(self.settings, "claw_enabled", False):
                    span.set_attribute("status", "disabled")
                    return self._result(
                        task,
                        TaskStatus.FAILED,
                        started_at,
                        error_message="Claw integration is disabled",
                    )
                payload = {"instruction": task.instruction}
                blocked_result = await self._check_critical_action(
                    task=task,
                    payload=payload,
                    started_at=started_at,
                    approved=approved,
                    tool_name="claw",
                    action="prompt",
                )
                if blocked_result:
                    span.set_attribute("status", "approval_required")
                    return blocked_result
                return await self._execute_claw(task, started_at)

            if task.agent == ModuleType.AGENTSCOPE and not getattr(
                self.settings,
                "agentscope_enabled",
                False,
            ):
                span.set_attribute("status", "disabled")
                return self._result(
                    task,
                    TaskStatus.FAILED,
                    started_at,
                    error_message="AgentScope integration is disabled",
                )

            payload = REMOTE_AGENT_SPECS[task.agent].build_payload(task)

            if task.agent in CRITICAL_ACTION_AGENTS:
                blocked_result = await self._check_critical_action(
                    task=task,
                    payload=payload,
                    started_at=started_at,
                    approved=approved,
                )
                if blocked_result:
                    span.set_attribute("status", "approval_required")
                    return blocked_result

            spec = REMOTE_AGENT_SPECS[task.agent]
            base_url = getattr(self.settings, spec.settings_attr)
            try:
                with start_span(
                    "agent.remote_call",
                    {
                        "workflow_id": workflow_id,
                        "session_id": session_id,
                        "agent_name": task.agent.value,
                    },
                ) as call_span:
                    response = await self.agents.post_json(
                        base_url=base_url,
                        path=spec.path,
                        payload=payload,
                        timeout=task.timeout_seconds
                        or self.settings.agent_http_timeout_seconds,
                    )
                    call_span.set_attribute("status", "success")
                await self._reflect_on_failure(task, response)
                status = (
                    TaskStatus.COMPLETED
                    if response.get("success", True)
                    else TaskStatus.FAILED
                )
                span.set_attribute("status", status.value)
                return self._result(
                    task,
                    status,
                    started_at,
                    output=response,
                    error_message=response.get("error"),
                )
            except Exception as exc:
                record_error(span, exc)
                logger.error(
                    "[%s] Task %s failed: %s", task.agent.value.upper(), task.id, exc
                )
                return self._result(
                    task,
                    TaskStatus.FAILED,
                    started_at,
                    error_message=str(exc),
                )

    async def _execute_claw(self, task: Task, started_at: float) -> TaskResult:
        """Execute a task using the Claw-Code CLI wrapper."""
        try:
            claw = ClawWrapper(settings=self.settings)
            result = await asyncio.to_thread(claw.prompt, task.instruction)
            return self._result(
                task,
                TaskStatus.COMPLETED,
                started_at,
                output={"success": True, "result": result},
            )
        except Exception as exc:
            logger.error("[CLAW] Execution failed: %s", exc)
            return self._result(
                task,
                TaskStatus.FAILED,
                started_at,
                error_message=f"Claw Error: {exc}",
            )

    async def _execute_mcp(
        self, task: Task, started_at: float, approved: bool
    ) -> TaskResult:
        """Execute a task using the Model Context Protocol (MCP)."""
        manager = get_mcp_manager()

        # Extract MCP specifics from context or instruction
        server = task.context.get("server")
        tool = task.context.get("tool")
        arguments = task.context.get("arguments", {})
        if not isinstance(arguments, dict):
            return self._result(
                task,
                TaskStatus.FAILED,
                started_at,
                error_message="MCP task arguments must be an object",
            )

        if not server or not tool:
            # Try to parse from instruction if not in context
            logger.info("[MCP] Attempting to parse server/tool from instruction")
            # Simple heuristic: "call server:tool with args"
            match = re.search(
                r"call\s+([\w-]+):([\w-]+)", task.instruction, re.IGNORECASE
            )
            if match:
                server, tool = match.groups()
            else:
                return self._result(
                    task,
                    TaskStatus.FAILED,
                    started_at,
                    error_message=(
                        "MCP task requires 'server' and 'tool' in context or "
                        "'call server:tool' in instruction"
                    ),
                )

        try:
            payload = {"server": server, "tool": tool, "arguments": arguments}
            blocked_result = await self._check_critical_action(
                task=task,
                payload=payload,
                started_at=started_at,
                approved=approved,
                tool_name=f"mcp:{server}",
                action=tool,
            )
            if blocked_result:
                return blocked_result

            logger.info("[MCP] Calling %s:%s", server, tool)
            result = await manager.call_tool(server, tool, arguments)
            return self._result(
                task,
                TaskStatus.COMPLETED,
                started_at,
                output={"success": True, "result": _serialize_mcp_result(result)},
            )
        except Exception as exc:
            logger.error("[MCP] Call failed: %s", exc)
            return self._result(
                task,
                TaskStatus.FAILED,
                started_at,
                error_message=f"MCP Error: {exc}",
            )

    async def _find_input_risk(
        self,
        instruction: str,
        workflow_id: str = "",
        session_id: str = "",
    ) -> Optional[str]:
        with start_span(
            "guardrail.agent_input_check",
            {
                "workflow_id": workflow_id,
                "session_id": session_id,
                "agent_name": "guardrail",
            },
        ) as span:
            try:
                verdict = await self.guardrails.guard_input(instruction)
                span.set_attribute(
                    "status", "safe" if verdict.get("safe", True) else "blocked"
                )
                if not verdict.get("safe", True):
                    return verdict.get("reason", "Malicious input pattern detected.")
                return None
            except Exception as exc:
                record_error(span, exc)
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
        tool_name: Optional[str] = None,
        action: Optional[str] = None,
    ) -> Optional[TaskResult]:
        workflow_id = str(task.context.get("workflow_id", ""))
        session_id = str(task.context.get("session_id", ""))
        resolved_tool = tool_name or task.agent.value
        resolved_action = action or task.instruction
        with start_span(
            "guardrail.tool_check",
            {
                "workflow_id": workflow_id,
                "session_id": session_id,
                "agent_name": task.agent.value,
                "tool_name": resolved_tool,
                "action": resolved_action[:120],
            },
        ) as span:
            try:
                verdict = await self.guardrails.guard_tool(
                    tool_name=resolved_tool,
                    action=resolved_action,
                    parameters=payload,
                )
                span.set_attribute("status", verdict.get("verdict", "unknown"))
            except Exception as exc:
                record_error(span, exc)
                return self._result(
                    task,
                    TaskStatus.FAILED,
                    started_at,
                    error_message=f"Guardrail service unavailable: {exc}",
                )

            if verdict.get("verdict") == "BLOCK":
                span.set_attribute("status", "blocked")
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
                with start_span(
                    "approval.request",
                    {
                        "workflow_id": workflow_id,
                        "session_id": session_id,
                        "agent_name": task.agent.value,
                        "tool_name": resolved_tool,
                    },
                ) as approval_span:
                    try:
                        approval = await self.approvals.create_approval(
                            task_id=task.id,
                            agent=task.agent.value,
                            action=task.instruction,
                            parameters=payload,
                            reason=verdict.get("reason"),
                        )
                        approval_span.set_attribute("status", "requested")
                    except Exception as exc:
                        record_error(approval_span, exc)
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


def _with_context(
    payload: dict[str, Any],
    task: Task,
    key: str = "context",
) -> dict[str, Any]:
    """Attach context only for service boundaries that accept it."""
    if task.context:
        payload[key] = task.context
    return payload


def _serialize_mcp_result(result: Any) -> Any:
    """Convert MCP SDK response objects into JSON-safe values."""
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if isinstance(result, dict):
        return {key: _serialize_mcp_result(value) for key, value in result.items()}
    if isinstance(result, (list, tuple)):
        return [_serialize_mcp_result(value) for value in result]
    if hasattr(result, "content"):
        return _serialize_mcp_result(result.content)
    return str(result)


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
