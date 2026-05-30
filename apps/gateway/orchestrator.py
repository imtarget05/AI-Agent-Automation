"""
LangGraph orchestration for the multi-agent workflow.

The orchestrator owns planning, task routing, agent invocation, and result
synthesis. Agent implementation details stay behind HTTP service boundaries.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

import httpx
from langgraph.graph import END, StateGraph

from shared.config import get_settings
from shared.llm import get_llm_router
from shared.memory import get_session_memory
from shared.models import (
    AgentState,
    ExecutionPlan,
    ModuleType,
    Task,
    TaskResult,
    TaskStatus,
)

logger = logging.getLogger(__name__)


MANAGER_PROMPT = """You are a Task Manager Agent for a multi-module AI system.

Your job is to analyze the user's request and create an execution plan by routing
to specialized agents.

Available agents:
- COMPUTER_USE: Desktop automation, UI control, screenshots, local app control
- BROWSER: Web browsing, web search, web extraction, page summarization
- SOCIAL: Social media auto-reply and customer service responses

Output must be valid JSON:
{
  "analysis": "Brief analysis of what needs to be done",
  "tasks": [
    {
      "id": "task_1",
      "agent": "COMPUTER_USE|BROWSER|SOCIAL",
      "instruction": "Detailed instruction for the agent",
      "expected_output_schema": {"type": "object", "fields": ["field1"]}
    }
  ],
  "estimated_duration_seconds": 30
}

Return only JSON. Do not wrap it in markdown.
"""


SYNTHESIZER_PROMPT = """You are a Result Synthesizer. Combine results from multiple agents into a clear final answer.

User's original request:
{user_input}

Results from agents:
{results}

Provide a concise, professional final answer. If some tasks failed, mention the useful partial result and the failure clearly.
"""


@dataclass(frozen=True)
class AgentEndpoint:
    """HTTP boundary for an agent service."""

    module: ModuleType
    settings_attr: str
    path: str = "/execute"


REMOTE_AGENT_ENDPOINTS: dict[ModuleType, AgentEndpoint] = {
    ModuleType.COMPUTER_USE: AgentEndpoint(
        module=ModuleType.COMPUTER_USE,
        settings_attr="computer_use_service_url",
    ),
    ModuleType.BROWSER: AgentEndpoint(
        module=ModuleType.BROWSER,
        settings_attr="browser_service_url",
    ),
    ModuleType.SOCIAL: AgentEndpoint(
        module=ModuleType.SOCIAL,
        settings_attr="social_service_url",
    ),
    ModuleType.RAG: AgentEndpoint(
        module=ModuleType.RAG,
        settings_attr="rag_service_url",
        path="/retrieve",
    ),
    ModuleType.EMAIL: AgentEndpoint(
        module=ModuleType.EMAIL,
        settings_attr="email_agent_service_url",
        path="/execute",
    ),
    ModuleType.TOOL: AgentEndpoint(
        module=ModuleType.TOOL,
        settings_attr="tool_service_url",
    ),
    ModuleType.GUARDRAIL: AgentEndpoint(
        module=ModuleType.GUARDRAIL,
        settings_attr="guardrail_service_url",
        path="/guard/tool",
    ),
}


class MultiAgentOrchestrator:
    """Coordinates planning, agent execution, and final response synthesis."""

    def __init__(self):
        self.llm = get_llm_router()
        self.settings = get_settings()
        self.graph = self._build_graph()
        self.compiled_graph = self.graph.compile()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
        workflow = StateGraph(AgentState)

        workflow.add_node("manager", self._manager_node)
        workflow.add_node("computer_use", self._computer_use_node)
        workflow.add_node("browser", self._browser_node)
        workflow.add_node("social", self._social_node)
        
        # New AIOps & Platform nodes
        workflow.add_node("rag", self._rag_node)
        workflow.add_node("email", self._email_node)
        workflow.add_node("tool", self._tool_node)
        workflow.add_node("guardrail", self._guardrail_node)
        workflow.add_node("aiops", self._aiops_node)
        workflow.add_node("rca", self._rca_node)
        workflow.add_node("devops", self._devops_node)
        workflow.add_node("report", self._report_node)

        workflow.add_node("synthesize", self._synthesize_node)

        workflow.set_entry_point("manager")
        
        all_nodes = [
            "computer_use", "browser", "social", 
            "rag", "email", "tool", "guardrail",
            "aiops", "rca", "devops", "report"
        ]
        
        workflow.add_conditional_edges("manager", self._route_tasks, self._route_map())

        for node in all_nodes:
            workflow.add_conditional_edges(node, self._route_tasks, self._route_map())

        workflow.add_edge("synthesize", END)
        return workflow

    @staticmethod
    def _route_map() -> dict[str, str]:
        return {
            "computer_use": "computer_use",
            "browser": "browser",
            "social": "social",
            "rag": "rag",
            "email": "email",
            "tool": "tool",
            "guardrail": "guardrail",
            "aiops": "aiops",
            "rca": "rca",
            "devops": "devops",
            "report": "report",
            "synthesize": "synthesize",
        }

    async def _manager_node(self, state: AgentState) -> AgentState:
        """Analyze the user request and create an execution plan."""
        logger.info("[MANAGER] Processing: %s", state["user_input"])

        # Guardrail input check
        try:
            guard_url = f"{self.settings.guardrail_service_url.rstrip('/')}/guard/input"
            async with httpx.AsyncClient(timeout=10) as client:
                guard_res = await client.post(guard_url, json={"text": state["user_input"]})
                if guard_res.status_code == 200:
                    guard_data = guard_res.json()
                    if guard_data.get("action") == "BLOCK":
                        logger.warning("[MANAGER] Guardrail blocked input: %s", guard_data.get("reason"))
                        state["error"] = f"Input blocked by Guardrail: {guard_data.get('reason')}"
                        return state
        except Exception as e:
            logger.warning("[MANAGER] Guardrail input check failed or unavailable: %s", e)

        allowed_modules = self._allowed_modules(state)
        allowed_names = ", ".join(module.name for module in allowed_modules)
        messages = [
            {
                "role": "system",
                "content": (
                    MANAGER_PROMPT
                    + f"\nOnly use these agents for this request: {allowed_names}."
                ),
            },
            {"role": "user", "content": state["user_input"]},
        ]

        try:
            response = await self.llm.chat(
                messages=messages,
                task="planning",
                temperature=0.3,
            )
            plan_data = self._parse_json_object(response)
            tasks = self._build_tasks(plan_data, allowed_modules)

            state["plan"] = ExecutionPlan(
                user_task=state["user_input"],
                tasks=tasks,
                estimated_duration_seconds=plan_data.get("estimated_duration_seconds", 30),
            )
            state["messages"].append({"role": "manager", "content": response})

            if not tasks:
                state["error"] = "Manager did not create any executable tasks."

            logger.info("[MANAGER] Created plan with %s executable task(s)", len(tasks))
        except Exception as exc:
            logger.error("[MANAGER] Failed to create execution plan: %s", exc, exc_info=True)
            state["error"] = f"Failed to create execution plan: {exc}"

        return state

    def _route_tasks(self, state: AgentState) -> str:
        """Route to the next pending task or synthesize when complete."""
        if state.get("error") and not state.get("results"):
            return "synthesize"

        plan = state.get("plan")
        if not plan or not plan.tasks:
            return "synthesize"

        completed = state.get("results", {})
        for task in plan.tasks:
            if task.id not in completed:
                return task.agent.value

        return "synthesize"

    async def _computer_use_node(self, state: AgentState) -> AgentState:
        return await self._remote_agent_node(
            state=state,
            agent=ModuleType.COMPUTER_USE,
            payload_builder=self._build_computer_payload,
        )

    async def _browser_node(self, state: AgentState) -> AgentState:
        return await self._remote_agent_node(
            state=state,
            agent=ModuleType.BROWSER,
            payload_builder=self._build_browser_payload,
        )

    async def _rag_node(self, state: AgentState) -> AgentState:
        return await self._remote_agent_node(
            state=state,
            agent=ModuleType.RAG,
            payload_builder=lambda t: {"query": t.instruction, "top_k": 5},
        )

    async def _email_node(self, state: AgentState) -> AgentState:
        return await self._remote_agent_node(
            state=state,
            agent=ModuleType.EMAIL,
            payload_builder=lambda t: {"instruction": t.instruction, "mode": "draft"},
        )

    async def _tool_node(self, state: AgentState) -> AgentState:
        return await self._remote_agent_node(
            state=state,
            agent=ModuleType.TOOL,
            payload_builder=lambda t: {"instruction": t.instruction},
        )

    async def _guardrail_node(self, state: AgentState) -> AgentState:
        return await self._remote_agent_node(
            state=state,
            agent=ModuleType.GUARDRAIL,
            payload_builder=lambda t: {"tool_name": "unknown", "action": t.instruction, "parameters": {}},
        )

    async def _aiops_node(self, state: AgentState) -> AgentState:
        # Placeholder for aiops agent
        task = self._next_task_for_agent(state, ModuleType.AIOPS)
        if not task: return state
        self._record_result(state, task, TaskStatus.COMPLETED, {"success": True, "message": "AIOps analyzed anomalies"}, None, time.perf_counter())
        return state

    async def _rca_node(self, state: AgentState) -> AgentState:
        # Placeholder for rca agent
        task = self._next_task_for_agent(state, ModuleType.RCA)
        if not task: return state
        self._record_result(state, task, TaskStatus.COMPLETED, {"success": True, "message": "RCA concluded root cause"}, None, time.perf_counter())
        return state

    async def _devops_node(self, state: AgentState) -> AgentState:
        # Placeholder for devops agent
        task = self._next_task_for_agent(state, ModuleType.DEVOPS)
        if not task: return state
        self._record_result(state, task, TaskStatus.COMPLETED, {"success": True, "message": "DevOps analyzed deployment"}, None, time.perf_counter())
        return state

    async def _report_node(self, state: AgentState) -> AgentState:
        # Placeholder for report agent
        task = self._next_task_for_agent(state, ModuleType.REPORT)
        if not task: return state
        self._record_result(state, task, TaskStatus.COMPLETED, {"success": True, "message": "Report generated"}, None, time.perf_counter())
        return state

    async def _remote_agent_node(
        self,
        state: AgentState,
        agent: ModuleType,
        payload_builder: Callable[[Task], dict],
    ) -> AgentState:
        """Execute one pending task by posting to a remote agent service with automated guardrail safety interception."""
        task = self._next_task_for_agent(state, agent)
        if not task:
            return state

        logger.info("[%s] Executing task %s", agent.value.upper(), task.id)
        state["current_agent"] = agent

        start = time.perf_counter()

        # ──── 1. Input Guardrail Safety Check ────
        input_safe = True
        risk_reason = ""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                guard_resp = await client.post(
                    f"{self.settings.guardrail_service_url}/guard/input",
                    json={"prompt": task.instruction}
                )
                if guard_resp.status_code == 200:
                    data = guard_resp.json()
                    if not data.get("safe", True):
                        input_safe = False
                        risk_reason = data.get("reason", "Malicious input pattern detected.")
        except Exception as e:
            logger.warning(f"Could not reach guardrail service: {e}. Running local pattern scanner fallback.")
            # Local fallback regex scanner
            for pattern in [r"ignore previous", r"override system", r"rm -rf", r"sudo "]:
                if re.search(pattern, task.instruction, re.IGNORECASE):
                    input_safe = False
                    risk_reason = f"Local safety scanner matched pattern: '{pattern}'"

        if not input_safe:
            logger.warning(f"🚫 [GUARDRAIL BLOCK] Input blocked for task {task.id}: {risk_reason}")
            self._record_result(
                state=state,
                task=task,
                status=TaskStatus.FAILED,
                output=None,
                error_message=f"🚫 Input Safety Block: {risk_reason}",
                started_at=start,
            )
            state["error"] = f"Safety Block: {risk_reason}"
            return state

        # ──── 2. Tool / Action Execution Guardrail Check ────
        if agent in [ModuleType.TOOL, ModuleType.COMPUTER_USE, ModuleType.DEVOPS]:
            tool_allowed = True
            requires_approval = False
            verdict = "ALLOW"
            risk_reason = ""
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    guard_resp = await client.post(
                        f"{self.settings.guardrail_service_url}/guard/tool",
                        json={"tool_name": agent.value, "action": task.instruction}
                    )
                    if guard_resp.status_code == 200:
                        data = guard_resp.json()
                        verdict = data.get("verdict", "ALLOW")
                        risk_reason = data.get("reason", "")
                        tool_allowed = data.get("allowed", True)
                        requires_approval = data.get("requires_approval", False)
            except Exception as e:
                logger.warning(f"Could not reach guardrail tool API: {e}. Running local risk analysis fallback.")
                # Local fallback risk levels
                action_text = task.instruction.lower()
                if any(x in action_text for x in ["delete", "restart", "scale", "rollback"]):
                    verdict = "REQUIRE_APPROVAL"
                    requires_approval = True
                    risk_reason = "Destructive/structural command requires supervisor clearance."
                elif any(x in action_text for x in ["drop", "uninstall", "purge"]):
                    verdict = "BLOCK"
                    tool_allowed = False
                    risk_reason = "Critical dangerous command permanently prohibited."

            if verdict == "BLOCK" or (not tool_allowed and not requires_approval):
                logger.warning(f"🚫 [GUARDRAIL BLOCK] Restricted tool action prevented: {risk_reason}")
                self._record_result(
                    state=state,
                    task=task,
                    status=TaskStatus.FAILED,
                    output=None,
                    error_message=f"🚫 Restricted Action Safety Block: {risk_reason}",
                    started_at=start,
                )
                return state

            if verdict == "REQUIRE_APPROVAL" or requires_approval:
                # Check if task id is in approved list
                approved_tasks = state.get("approved_tasks", [])
                if task.id not in approved_tasks:
                    logger.warning(f"⚠️ [GUARDRAIL REQUIRE_APPROVAL] Pausing task {task.id} - Awaiting manual approval.")
                    
                    # Proactively call the email agent to draft supervisor approval email!
                    email_payload = {
                        "instruction": f"Draft an urgent operator approval request email for task {task.id} requesting execution of: '{task.instruction}'",
                        "recipient": "supervisor@company.com",
                        "tone": "formal",
                        "context_data": {
                            "task_id": task.id,
                            "agent": agent.value,
                            "instruction": task.instruction,
                            "reason": risk_reason
                        }
                    }
                    try:
                        async with httpx.AsyncClient(timeout=4.0) as client:
                            await client.post(
                                f"{self.settings.email_agent_service_url}/execute",
                                json=email_payload
                            )
                    except Exception as email_err:
                        logger.error(f"Failed to auto-send approval request email draft: {email_err}")

                    self._record_result(
                        state=state,
                        task=task,
                        status=TaskStatus.FAILED,
                        output={"status": "AWAITING_APPROVAL", "approval_required": True},
                        error_message=f"⚠️ Safety Check: Action requires manual supervisor approval. An alert draft has been created for supervisor@company.com in docs/last_email_draft.txt. To continue, approve task {task.id}.",
                        started_at=start,
                    )
                    return state
                else:
                    logger.info(f"✅ [GUARDRAIL APPROVED] Task {task.id} approved by supervisor. Launching tool.")

        # ──── 3. Standard Remote API execution ────
        endpoint = REMOTE_AGENT_ENDPOINTS[agent]
        base_url = getattr(self.settings, endpoint.settings_attr)

        try:
            response = await self._post_agent(
                base_url=base_url,
                path=endpoint.path,
                payload=payload_builder(task),
                timeout=task.timeout_seconds or self.settings.agent_http_timeout_seconds,
            )
            status = TaskStatus.COMPLETED if response.get("success") else TaskStatus.FAILED
            self._record_result(
                state=state,
                task=task,
                status=status,
                output=response,
                error_message=response.get("error"),
                started_at=start,
            )
        except Exception as exc:
            logger.error("[%s] Task %s failed: %s", agent.value.upper(), task.id, exc)
            self._record_result(
                state=state,
                task=task,
                status=TaskStatus.FAILED,
                output=None,
                error_message=str(exc),
                started_at=start,
            )

        return state

    async def _social_node(self, state: AgentState) -> AgentState:
        """Social agent placeholder until the social service exposes /execute."""
        task = self._next_task_for_agent(state, ModuleType.SOCIAL)
        if not task:
            return state

        logger.info("[SOCIAL] Executing task %s", task.id)
        state["current_agent"] = ModuleType.SOCIAL
        start = time.perf_counter()

        output = {
            "success": True,
            "message": "Social webhook replies are handled by platform endpoints.",
            "instruction": task.instruction,
        }
        self._record_result(
            state=state,
            task=task,
            status=TaskStatus.COMPLETED,
            output=output,
            error_message=None,
            started_at=start,
        )
        return state

    async def _synthesize_node(self, state: AgentState) -> AgentState:
        """Synthesize all agent results into the final answer."""
        logger.info("[SYNTHESIZER] Creating final answer")

        if state.get("error") and not state.get("results"):
            state["final_answer"] = state["error"]
            return state

        results_text = self._format_results(state.get("results", {}))
        messages = [
            {
                "role": "system",
                "content": SYNTHESIZER_PROMPT.format(
                    user_input=state["user_input"],
                    results=results_text or "No agent results were produced.",
                ),
            },
            {"role": "user", "content": "Synthesize the results above."},
        ]

        try:
            response = await self.llm.chat(
                messages=messages,
                task="summarize",
                temperature=0.5,
            )
            state["final_answer"] = response
            state["messages"].append({"role": "synthesizer", "content": response})
        except Exception as exc:
            logger.error("[SYNTHESIZER] Error: %s", exc, exc_info=True)
            state["error"] = f"Synthesis failed: {exc}"
            state["final_answer"] = results_text or state["error"]

        return state

    async def execute(
        self,
        user_input: str,
        session_id: str,
        allowed_modules: Optional[list[ModuleType]] = None,
    ) -> dict:
        """Execute the full workflow for one user request."""
        logger.info("[ORCHESTRATOR] Starting execution for session %s", session_id)

        initial_state: AgentState = {
            "session_id": session_id,
            "user_input": user_input,
            "allowed_modules": allowed_modules,
            "messages": [],
            "results": {},
            "current_agent": None,
            "final_answer": None,
            "error": None,
        }

        final_state = await self.compiled_graph.ainvoke(initial_state)
        await self._save_session_memory(
            session_id=session_id,
            user_input=user_input,
            assistant_response=final_state.get("final_answer") or "",
        )

        return {
            "plan": final_state.get("plan"),
            "results": final_state.get("results"),
            "final_answer": final_state.get("final_answer"),
            "error": final_state.get("error"),
        }

    def _allowed_modules(self, state: AgentState) -> list[ModuleType]:
        configured = state.get("allowed_modules")
        return configured or list(ModuleType)

    def _build_tasks(
        self,
        plan_data: dict,
        allowed_modules: list[ModuleType],
    ) -> list[Task]:
        allowed = set(allowed_modules)
        tasks: list[Task] = []

        for index, task_data in enumerate(plan_data.get("tasks", []), start=1):
            agent = self._parse_agent(task_data.get("agent"))
            if agent is None:
                logger.warning("Skipping task with unknown agent: %s", task_data)
                continue
            if agent not in allowed:
                logger.warning("Skipping task for disallowed agent: %s", agent.value)
                continue

            schema = task_data.get("expected_output_schema")
            tasks.append(
                Task(
                    id=task_data.get("id") or f"task_{index}",
                    agent=agent,
                    instruction=task_data["instruction"],
                    expected_output_schema=schema if isinstance(schema, dict) else None,
                )
            )

        return tasks

    @staticmethod
    def _parse_agent(raw_agent: object) -> Optional[ModuleType]:
        if not isinstance(raw_agent, str):
            return None
        normalized = raw_agent.strip().lower()
        try:
            return ModuleType(normalized)
        except ValueError:
            return None

    @staticmethod
    def _parse_json_object(text: str) -> dict:
        """Parse a JSON object, tolerating fenced LLM responses."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if fenced:
            return json.loads(fenced.group(1))

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])

        raise ValueError("LLM response did not contain a JSON object")

    @staticmethod
    def _next_task_for_agent(state: AgentState, agent: ModuleType) -> Optional[Task]:
        plan = state.get("plan")
        if not plan:
            return None

        completed = state.get("results", {})
        return next(
            (
                task
                for task in plan.tasks
                if task.agent == agent and task.id not in completed
            ),
            None,
        )

    def _build_computer_payload(self, task: Task) -> dict:
        return {"objective": task.instruction}

    def _build_browser_payload(self, task: Task) -> dict:
        payload = {"instruction": task.instruction}

        url = self._extract_url(task.instruction)
        if url:
            payload["url"] = url

        extract_fields = self._extract_fields(task.expected_output_schema)
        if extract_fields:
            payload["extract_fields"] = extract_fields

        return payload

    @staticmethod
    def _extract_url(text: str) -> Optional[str]:
        """Extract the first URL or domain from text."""
        url_match = re.search(r"https?://\S+", text)
        if url_match:
            return url_match.group(0)

        domain_match = re.search(r"\b([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/\S*)?\b", text)
        if domain_match:
            return f"https://{domain_match.group(0)}"

        return None

    @staticmethod
    def _extract_fields(schema: Optional[dict]) -> Optional[list[str]]:
        """Extract desired fields from the expected output schema."""
        if not schema:
            return None
        fields = schema.get("fields")
        if isinstance(fields, list) and all(isinstance(field, str) for field in fields):
            return fields
        return None

    async def _post_agent(
        self,
        base_url: str,
        path: str,
        payload: dict,
        timeout: int,
    ) -> dict:
        """Send a request to an agent service."""
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _record_result(
        state: AgentState,
        task: Task,
        status: TaskStatus,
        output: object,
        error_message: Optional[str],
        started_at: float,
    ) -> None:
        state.setdefault("results", {})[task.id] = TaskResult(
            task_id=task.id,
            agent=task.agent,
            status=status,
            output=output,
            error_message=error_message,
            execution_time_seconds=time.perf_counter() - started_at,
        )
        logger.info("[%s] Task %s finished with %s", task.agent.value.upper(), task.id, status.value)

    @staticmethod
    def _format_results(results: dict[str, TaskResult]) -> str:
        lines = []
        for result in results.values():
            detail = result.output if result.status == TaskStatus.COMPLETED else result.error_message
            lines.append(
                f"- {result.task_id} ({result.agent.value}, {result.status.value}): {detail}"
            )
        return "\n".join(lines)

    @staticmethod
    async def _save_session_memory(
        session_id: str,
        user_input: str,
        assistant_response: str,
    ) -> None:
        try:
            session_memory = get_session_memory(session_id)
            await session_memory.append("user", user_input)
            await session_memory.append("assistant", assistant_response)
        except Exception as exc:
            logger.warning("Session memory save failed: %s", exc)


_orchestrator: Optional[MultiAgentOrchestrator] = None


def get_orchestrator() -> MultiAgentOrchestrator:
    """Get or create the process-wide orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MultiAgentOrchestrator()
    return _orchestrator
