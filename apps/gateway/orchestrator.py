"""LangGraph orchestration for the multi-agent workflow.

The orchestrator owns planning, routing, and result synthesis. Remote execution
details stay behind the AgentExecutionService application boundary.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

from langgraph.graph import END, StateGraph

from apps.gateway.agent_execution import AgentExecutionService
from shared.config import get_settings
from shared.guardrails import GuardrailClient
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

Analyze the user's request and create an execution plan by routing work to
specialized agents.

Available agents:
- RAG: retrieve docs, runbooks, README files, and architecture notes
- AIOPS: detect anomalies from metrics, logs, and events
- RCA: analyze root causes
- DEVOPS: analyze deployment, Kubernetes, and CI/CD failures
- EMAIL: draft or send incident email reports
- TOOL: invoke Kubernetes, Prometheus, and email tools
- GUARDRAIL: check potentially dangerous actions
- REPORT: create incident reports
- BROWSER: browse, search, extract, and summarize web pages
- COMPUTER_USE: automate desktop UI actions and screenshots
- SOCIAL: reply to customer messages on social platforms

Output must be valid JSON:
{
  "analysis": "Brief analysis of what needs to be done",
  "tasks": [
    {
      "id": "task_1",
      "agent": "RAG|AIOPS|RCA|DEVOPS|EMAIL|TOOL|GUARDRAIL|REPORT|COMPUTER_USE|BROWSER|SOCIAL",
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


class MultiAgentOrchestrator:
    """Coordinate planning, agent execution, and final response synthesis."""

    def __init__(
        self,
        llm=None,
        settings=None,
        guardrails=None,
        agent_execution=None,
    ):
        self.llm = llm or get_llm_router()
        self.settings = settings or get_settings()
        self.guardrails = guardrails or GuardrailClient(
            self.settings.guardrail_service_url
        )
        self.agent_execution = agent_execution or AgentExecutionService(
            settings=self.settings,
            llm=self.llm,
            guardrails=self.guardrails,
        )
        self.graph = self._build_graph()
        self.compiled_graph = self.graph.compile()

    def _build_graph(self) -> StateGraph:
        """Build the workflow while keeping infrastructure outside the graph."""
        workflow = StateGraph(AgentState)

        workflow.add_node("manager", self._manager_node)
        workflow.add_node("computer_use", self._computer_use_node)
        workflow.add_node("browser", self._browser_node)
        workflow.add_node("social", self._social_node)
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
        workflow.add_conditional_edges("manager", self._route_tasks, self._route_map())
        for node in self._agent_nodes():
            workflow.add_conditional_edges(node, self._route_tasks, self._route_map())

        workflow.add_edge("synthesize", END)
        return workflow

    @staticmethod
    def _agent_nodes() -> tuple[str, ...]:
        return (
            "computer_use",
            "browser",
            "social",
            "rag",
            "email",
            "tool",
            "guardrail",
            "aiops",
            "rca",
            "devops",
            "report",
        )

    @classmethod
    def _route_map(cls) -> dict[str, str]:
        return {node: node for node in (*cls._agent_nodes(), "synthesize")}

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

    async def _manager_node(self, state: AgentState) -> dict:
        """Analyze the user request and create an execution plan."""
        logger.info("[MANAGER] Processing: %s", state["user_input"])
        updates = {"messages": []}
        manager_input = state["user_input"]

        try:
            guard_data = await self.guardrails.guard_input(manager_input)
            if not guard_data.get("safe", True):
                reason = guard_data.get("reason")
                logger.warning("[MANAGER] Guardrail blocked input: %s", reason)
                return {"error": f"Input blocked by Guardrail: {reason}"}
            manager_input = guard_data.get("anonymized_prompt", manager_input)
        except Exception as exc:
            logger.warning("[MANAGER] Guardrail input check unavailable: %s", exc)

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
            {"role": "user", "content": manager_input},
        ]

        try:
            response = await self.llm.chat(
                messages=messages,
                task="planning",
                temperature=0.3,
            )
            plan_data = self._parse_json_object(response)
            tasks = self._build_tasks(plan_data, allowed_modules)

            updates["plan"] = ExecutionPlan(
                user_task=state["user_input"],
                tasks=tasks,
                estimated_duration_seconds=plan_data.get(
                    "estimated_duration_seconds",
                    30,
                ),
            )
            updates["messages"].append({"role": "manager", "content": response})
            if not tasks:
                updates["error"] = "Manager did not create any executable tasks."

            logger.info("[MANAGER] Created plan with %s executable task(s)", len(tasks))
        except Exception as exc:
            logger.error(
                "[MANAGER] Failed to create execution plan: %s",
                exc,
                exc_info=True,
            )
            updates["error"] = f"Failed to create execution plan: {exc}"
        return updates

    async def _computer_use_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.COMPUTER_USE)

    async def _browser_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.BROWSER)

    async def _rag_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.RAG)

    async def _email_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.EMAIL)

    async def _tool_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.TOOL)

    async def _guardrail_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.GUARDRAIL)

    async def _aiops_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.AIOPS)

    async def _rca_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.RCA)

    async def _devops_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.DEVOPS)

    async def _report_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.REPORT)

    async def _remote_agent_node(
        self,
        state: AgentState,
        agent: ModuleType,
    ) -> dict:
        """Execute one planned task through the application service."""
        task = self._next_task_for_agent(state, agent)
        if not task:
            return {}

        logger.info("[%s] Executing task %s", agent.value.upper(), task.id)
        result = await self.agent_execution.execute(
            task,
            approved=task.id in state.get("approved_tasks", []),
        )
        return {"results": {task.id: result}}

    async def _social_node(self, state: AgentState) -> dict:
        """Return a stable result for the webhook-only social integration."""
        task = self._next_task_for_agent(state, ModuleType.SOCIAL)
        if not task:
            return {}

        started_at = time.perf_counter()
        result = TaskResult(
            task_id=task.id,
            agent=task.agent,
            status=TaskStatus.COMPLETED,
            output={
                "success": True,
                "message": "Social webhook replies are handled by platform endpoints.",
                "instruction": task.instruction,
            },
            execution_time_seconds=time.perf_counter() - started_at,
        )
        return {"results": {task.id: result}}

    async def _synthesize_node(self, state: AgentState) -> dict:
        """Synthesize all agent results into the final answer."""
        logger.info("[SYNTHESIZER] Creating final answer")
        if state.get("error") and not state.get("results"):
            return {"final_answer": state["error"]}

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
            if self.settings.accuracy_guardrail_enabled:
                response = await self._audit_answer(response, results_text)
            return {
                "final_answer": response,
                "messages": [{"role": "synthesizer", "content": response}],
            }
        except Exception as exc:
            logger.error("[SYNTHESIZER] Error: %s", exc, exc_info=True)
            return {"final_answer": results_text or f"Synthesis failed: {exc}"}

    async def _audit_answer(self, answer: str, results_text: str) -> str:
        """Correct unsupported claims while keeping audit failure non-fatal."""
        prompt = f"""You are an Accuracy Auditor. Compare the final answer with the raw agent results.
Final Answer: {answer}
Raw Agent Results: {results_text}

Are there factual contradictions or hallucinations in the final answer that are
not supported by the results? If there are errors, return a corrected answer.
If the final answer is accurate and supported, reply with 'STRICTLY_ACCURATE'."""
        try:
            audit = await self.llm.chat(
                [{"role": "user", "content": prompt}],
                task="summarize",
            )
        except Exception as exc:
            logger.warning("[SYNTHESIZER] Accuracy audit failed: %s", exc)
            return answer

        if "STRICTLY_ACCURATE" in audit:
            return answer
        logger.warning("[SYNTHESIZER] Accuracy audit corrected the answer.")
        return audit

    async def execute(
        self,
        user_input: str,
        session_id: str,
        allowed_modules: Optional[list[ModuleType]] = None,
    ) -> dict:
        """Execute the full workflow for one user request."""
        logger.info("[ORCHESTRATOR] Starting execution for session %s", session_id)
        memory = get_session_memory(session_id)
        history = await memory.get_messages()
        approved_tasks = await memory.get_approved_tasks()

        initial_state: AgentState = {
            "session_id": session_id,
            "user_input": user_input,
            "allowed_modules": allowed_modules,
            "messages": history,
            "results": {},
            "current_agent": None,
            "final_answer": None,
            "error": None,
            "approved_tasks": approved_tasks,
        }
        final_state = await self.compiled_graph.ainvoke(initial_state)

        if final_state.get("final_answer"):
            await memory.append("user", user_input)
            await memory.append("assistant", final_state["final_answer"])

        return {
            "plan": final_state.get("plan"),
            "results": final_state.get("results"),
            "final_answer": final_state.get("final_answer"),
            "error": final_state.get("error"),
        }

    @staticmethod
    def _allowed_modules(state: AgentState) -> list[ModuleType]:
        configured = state.get("allowed_modules")
        return list(ModuleType) if configured is None else configured

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
        try:
            return ModuleType(raw_agent.strip().lower())
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
    def _next_task_for_agent(
        state: AgentState,
        agent: ModuleType,
    ) -> Optional[Task]:
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

    @staticmethod
    def _format_results(results: dict[str, TaskResult]) -> str:
        lines = []
        for result in results.values():
            detail = (
                result.output
                if result.status == TaskStatus.COMPLETED
                else result.error_message
            )
            lines.append(
                f"- {result.task_id} ({result.agent.value}, {result.status.value}): {detail}"
            )
        return "\n".join(lines)


_orchestrator: Optional[MultiAgentOrchestrator] = None


def get_orchestrator() -> MultiAgentOrchestrator:
    """Get or create the process-wide orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MultiAgentOrchestrator()
    return _orchestrator
