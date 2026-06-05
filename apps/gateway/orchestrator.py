"""LangGraph orchestration for the dynamic multi-agent workflow.

The orchestrator owns planning, dynamic supervision, parallel routing, and result synthesis.
"""

from __future__ import annotations

import json
import re
import time
from typing import Optional
from uuid import uuid4

from langgraph.graph import END, StateGraph

from apps.gateway.agent_execution import AgentExecutionService
from shared.config import get_settings
from shared.guardrails import GuardrailClient
from shared.llm import get_llm_router
from shared.memory import get_long_term_memory, get_session_memory
from shared.cost.token_budget import BudgetExceededError, get_tracker, remove_tracker
from shared.observability.logging import get_log_context, get_logger, set_log_context
from shared.observability.tracing import record_error, start_span
from shared.models import (
    AgentState,
    ExecutionPlan,
    ModuleType,
    Task,
    TaskResult,
    TaskStatus,
)

logger = get_logger(__name__)


SUPERVISOR_PROMPT = """You are a Multi-Agent Supervisor for an AIOps and Automation system.
Your goal is to solve the user's request by coordinating specialized agents.

Analyze the user's request and the results of any previously executed tasks to determine the next steps.
You can delegate multiple tasks to different agents to run in PARALLEL if they are independent.

Available agents:
- RAG: retrieve docs, runbooks, README files, and architecture notes
- AIOPS: detect anomalies from metrics, logs, and events
- RCA: analyze root causes
- DEVOPS: analyze deployment, Kubernetes, and CI/CD failures
- EMAIL: draft or send incident email reports
- TOOL: invoke Kubernetes, Prometheus, and email tools
- MCP: use external Model Context Protocol tools (Google Search, GitHub, Slack, etc.)
- GUARDRAIL: check potentially dangerous actions
- REPORT: create incident reports
- BROWSER: browse, search, extract, and summarize web pages
- COMPUTER_USE: automate desktop UI actions and screenshots
- SOCIAL: reply to customer messages on social platforms

Output must be valid JSON:
{
  "analysis": "Brief analysis of current progress and next steps",
  "action": "DELEGATE|SYNTHESIZE",
  "tasks": [
    {
      "id": "task_id",
      "agent": "RAG|AIOPS|RCA|DEVOPS|EMAIL|TOOL|MCP|GUARDRAIL|REPORT|COMPUTER_USE|BROWSER|SOCIAL",
      "instruction": "Detailed instruction for the agent. For MCP, use 'call server:tool' format.",
      "context": {"server": "MCP server name", "tool": "MCP tool name", "arguments": {}},
      "context_from": ["task_id_1", "task_id_2"]
    }
  ],
  "final_answer": "Provide only if action is SYNTHESIZE"
}

If all tasks are done and you have enough information, use action 'SYNTHESIZE'.
If you need more information or actions, use action 'DELEGATE'.
"""


SYNTHESIZER_PROMPT = """You are a Result Synthesizer. Combine results from multiple agents into a clear final answer.

User's original request:
{user_input}

Results from agents:
{results}

Provide a concise, professional final answer. If some tasks failed, mention the useful partial result and the failure clearly.
"""


class MultiAgentOrchestrator:
    """Coordinate dynamic planning, parallel agent execution, and result synthesis."""

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
        """Build a dynamic supervisor-led graph with parallel fan-out."""
        workflow = StateGraph(AgentState)

        workflow.add_node("supervisor", self._supervisor_node)
        workflow.add_node("computer_use", self._computer_use_node)
        workflow.add_node("browser", self._browser_node)
        workflow.add_node("social", self._social_node)
        workflow.add_node("rag", self._rag_node)
        workflow.add_node("email", self._email_node)
        workflow.add_node("tool", self._tool_node)
        workflow.add_node("mcp", self._mcp_node)
        workflow.add_node("guardrail", self._guardrail_node)
        workflow.add_node("aiops", self._aiops_node)
        workflow.add_node("rca", self._rca_node)
        workflow.add_node("devops", self._devops_node)
        workflow.add_node("report", self._report_node)
        workflow.add_node("agentscope", self._agentscope_node)
        workflow.add_node("claw", self._claw_node)
        workflow.add_node("synthesize", self._synthesize_node)

        workflow.set_entry_point("supervisor")

        # Supervisor decides which agents to run or to synthesize
        workflow.add_conditional_edges(
            "supervisor",
            self._route_tasks,
            self._route_map(),
        )

        # All agents return to the supervisor for re-evaluation
        for node in self._agent_nodes():
            workflow.add_edge(node, "supervisor")

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
            "mcp",
            "guardrail",
            "aiops",
            "rca",
            "devops",
            "report",
            "agentscope",
            "claw",
        )

    @classmethod
    def _route_map(cls) -> dict[str, str]:
        """Map every agent node automatically so new modules cannot be omitted."""
        return {node: node for node in (*cls._agent_nodes(), "synthesize")}

    def _route_tasks(self, state: AgentState) -> list[str] | str:
        """Route to one or more agents in parallel, or synthesize."""
        if state.get("is_complete") or state.get("error"):
            return "synthesize"

        next_tasks = state.get("next_tasks", [])
        if not next_tasks:
            return "synthesize"

        plan = state.get("plan")
        if not plan:
            return "synthesize"

        nodes_to_run = []
        completed = state.get("results", {})
        for task_id in next_tasks:
            task = next((t for t in plan.tasks if t.id == task_id), None)
            if task and task.id not in completed:
                nodes_to_run.append(task.agent.value)

        return nodes_to_run if nodes_to_run else "synthesize"

    async def _supervisor_node(self, state: AgentState) -> dict:
        """Analyze current state and decide the next set of tasks or final answer."""
        workflow_id = state.get("workflow_id", "")
        session_id = state.get("session_id", "")
        with start_span(
            "orchestrator.supervisor",
            {
                "workflow_id": workflow_id,
                "session_id": session_id,
                "agent_name": "supervisor",
            },
        ) as span:
            logger.info("[SUPERVISOR] Evaluating progress...")
            results = state.get("results", {})
            results_summary = self._format_results(results)
            history = state.get("messages", [])
            iterations = state.get("supervisor_iterations", 0) + 1
            span.set_attribute("supervisor_iterations", iterations)
            if iterations > self.settings.orchestrator_max_iterations:
                span.set_attribute("status", "iteration_limit")
                return {
                    "error": "Supervisor iteration limit reached.",
                    "is_complete": True,
                    "supervisor_iterations": iterations,
                }

            manager_input = state["user_input"]
            if not results:
                with start_span(
                    "guardrail.input_check",
                    {
                        "workflow_id": workflow_id,
                        "session_id": session_id,
                        "agent_name": "guardrail",
                    },
                ) as guard_span:
                    try:
                        guard_data = await self.guardrails.guard_input(manager_input)
                        guard_span.set_attribute(
                            "status",
                            "safe" if guard_data.get("safe", True) else "blocked",
                        )
                        if not guard_data.get("safe", True):
                            reason = guard_data.get("reason")
                            logger.warning(
                                "[SUPERVISOR] Guardrail blocked input: %s", reason
                            )
                            return {
                                "error": f"Input blocked by Guardrail: {reason}",
                                "is_complete": True,
                            }
                        manager_input = guard_data.get(
                            "anonymized_prompt", manager_input
                        )
                    except Exception as exc:
                        record_error(guard_span, exc)
                        logger.warning("[SUPERVISOR] Guardrail unavailable: %s", exc)

            open_source_context = state.get("open_source_context")
            if open_source_context is None:
                open_source_context = await self._open_source_context(
                    manager_input,
                    workflow_id=workflow_id,
                    session_id=session_id,
                )

            allowed_modules = self._allowed_modules(state)
            allowed_names = ", ".join(module.name for module in allowed_modules)

            system_prompt = (
                SUPERVISOR_PROMPT + f"\nOnly use these agents: {allowed_names}."
            )
            configured_mcp_servers = sorted(self.settings.mcp_servers)
            if ModuleType.MCP in allowed_modules and self.settings.mcp_enabled:
                if configured_mcp_servers:
                    system_prompt += (
                        "\nConfigured MCP servers: "
                        + ", ".join(configured_mcp_servers)
                        + ". Delegate MCP work only to these servers."
                    )
                else:
                    system_prompt += (
                        "\nNo MCP servers are configured. Do not delegate MCP tasks."
                    )
            if ModuleType.AGENTSCOPE in allowed_modules:
                system_prompt += (
                    "\nAGENTSCOPE is available for complex multi-agent reasoning."
                )
            if ModuleType.CLAW in allowed_modules:
                system_prompt += "\nCLAW is available for approved code-related CLI tasks."
            if open_source_context:
                system_prompt += (
                    "\n\nLocal open-source references relevant to this request:\n"
                    f"{open_source_context}"
                )
            if results_summary:
                system_prompt += f"\n\nResults so far:\n{results_summary}"

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": manager_input},
            ]
            for msg in history:
                if msg["role"] in ("supervisor", "assistant"):
                    messages.insert(-1, msg)

            try:
                response = await self.llm.chat(
                    messages=messages,
                    task="planning",
                    temperature=0.2,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    agent_name="supervisor",
                )
                decision = self._parse_json_object(response)

                updates = {
                    "messages": [{"role": "supervisor", "content": response}],
                    "supervisor_iterations": iterations,
                    "open_source_context": open_source_context,
                }

                if decision.get("action") == "SYNTHESIZE":
                    updates["is_complete"] = True
                    updates["final_answer"] = decision.get("final_answer")
                    span.set_attribute("status", "synthesize")
                    return updates

                new_tasks = self._build_tasks(decision, allowed_modules)

                current_plan = state.get("plan")
                if current_plan:
                    existing_ids = {t.id for t in current_plan.tasks}
                    for nt in new_tasks:
                        if nt.id not in existing_ids:
                            current_plan.tasks.append(nt)
                else:
                    current_plan = ExecutionPlan(
                        user_task=state["user_input"],
                        tasks=new_tasks,
                        estimated_duration_seconds=30,
                    )

                updates["plan"] = current_plan
                updates["next_tasks"] = [t.id for t in new_tasks]

                logger.info("[SUPERVISOR] Delegating %d tasks", len(new_tasks))
                span.set_attribute("status", "success")
                span.set_attribute("delegated_task_count", len(new_tasks))
                return updates

            except BudgetExceededError as exc:
                span.set_attribute("status", "budget_exceeded")
                return {
                    "error": exc.to_response(),
                    "is_complete": True,
                    "open_source_context": open_source_context,
                }
            except Exception as exc:
                record_error(span, exc)
                logger.error("[SUPERVISOR] Failed: %s", exc)
                return {
                    "error": f"Supervisor failure: {exc}",
                    "is_complete": True,
                    "open_source_context": open_source_context,
                }

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

    async def _mcp_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.MCP)

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

    async def _agentscope_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.AGENTSCOPE)

    async def _claw_node(self, state: AgentState) -> dict:
        return await self._remote_agent_node(state, ModuleType.CLAW)

    async def _remote_agent_node(
        self,
        state: AgentState,
        agent: ModuleType,
    ) -> dict:
        """Execute all pending tasks for this agent type that are in next_tasks."""
        plan = state.get("plan")
        if not plan:
            return {}

        next_task_ids = set(state.get("next_tasks", []))
        results = {}
        workflow_id = state.get("workflow_id", "")
        session_id = state.get("session_id", "")

        for task in plan.tasks:
            if (
                task.agent == agent
                and task.id in next_task_ids
                and task.id not in state.get("results", {})
            ):
                with start_span(
                    "langgraph.node.execute",
                    {
                        "workflow_id": workflow_id,
                        "session_id": session_id,
                        "agent_name": agent.value,
                        "task_id": task.id,
                    },
                ) as span:
                    logger.info("[%s] Executing task %s", agent.value.upper(), task.id)

                    task.context.setdefault("workflow_id", workflow_id)
                    task.context.setdefault("session_id", session_id)

                    # Enrich task context from previous results
                    if task.context_from:
                        for ref_id in task.context_from:
                            ref_result = state.get("results", {}).get(ref_id)
                            if ref_result:
                                self._merge_context_result(
                                    task.context, ref_id, ref_result.output
                                )

                    result = await self.agent_execution.execute(
                        task,
                        approved=task.id in state.get("approved_tasks", []),
                    )
                    span.set_attribute("status", result.status.value)
                    if result.error_message:
                        span.set_attribute("error_type", "TaskExecutionError")
                    results[task.id] = result

        return {"results": results}

    async def _social_node(self, state: AgentState) -> dict:
        """Return a stable result for the webhook-only social integration."""
        plan = state.get("plan")
        if not plan:
            return {}

        next_task_ids = set(state.get("next_tasks", []))
        results = {}

        for task in plan.tasks:
            if task.agent == ModuleType.SOCIAL and task.id in next_task_ids:
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
                results[task.id] = result

        return {"results": results}

    async def _synthesize_node(self, state: AgentState) -> dict:
        """Synthesize all agent results into the final answer."""
        if state.get("final_answer"):
            return {
                "messages": [{"role": "synthesizer", "content": state["final_answer"]}]
            }

        workflow_id = state.get("workflow_id", "")
        session_id = state.get("session_id", "")
        with start_span(
            "orchestrator.synthesize",
            {
                "workflow_id": workflow_id,
                "session_id": session_id,
                "agent_name": "synthesizer",
            },
        ) as span:
            logger.info("[SYNTHESIZER] Creating final answer")
            if state.get("error") and not state.get("results"):
                span.set_attribute("status", "error_only")
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
                    workflow_id=workflow_id,
                    session_id=session_id,
                    agent_name="synthesizer",
                )
                if self.settings.accuracy_guardrail_enabled:
                    response = await self._audit_answer(
                        response,
                        results_text,
                        workflow_id=workflow_id,
                        session_id=session_id,
                    )
                span.set_attribute("status", "success")
                return {
                    "final_answer": response,
                    "messages": [{"role": "synthesizer", "content": response}],
                }
            except BudgetExceededError as exc:
                span.set_attribute("status", "budget_exceeded")
                return {"final_answer": exc.to_response(), "error": exc.to_response()}
            except Exception as exc:
                record_error(span, exc)
                logger.error("[SYNTHESIZER] Error: %s", exc, exc_info=True)
                return {"final_answer": results_text or f"Synthesis failed: {exc}"}

    async def _audit_answer(
        self,
        answer: str,
        results_text: str,
        workflow_id: str = "",
        session_id: str = "",
    ) -> str:
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
                workflow_id=workflow_id,
                session_id=session_id,
                agent_name="accuracy_auditor",
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
        workflow_id = str(uuid4())
        existing_context = get_log_context()
        set_log_context(
            request_id=existing_context.get("request_id", ""),
            workflow_id=workflow_id,
            session_id=session_id,
            tenant_id=existing_context.get("tenant_id", ""),
            user_id=existing_context.get("user_id", ""),
        )
        with start_span(
            "orchestrator.workflow",
            {
                "workflow_id": workflow_id,
                "session_id": session_id,
                "tenant_id": existing_context.get("tenant_id", ""),
                "user_id": existing_context.get("user_id", ""),
            },
        ) as span:
            logger.info("[ORCHESTRATOR] Starting execution for session %s", session_id)
            memory = get_session_memory(session_id)
            history = await memory.get_messages()
            approved_tasks = await memory.get_approved_tasks()
            get_tracker(workflow_id)

            initial_state: AgentState = {
                "session_id": session_id,
                "workflow_id": workflow_id,
                "user_input": user_input,
                "allowed_modules": allowed_modules,
                "messages": history,
                "results": {},
                "next_tasks": [],
                "current_tasks": [],
                "final_answer": None,
                "error": None,
                "approved_tasks": approved_tasks,
                "is_complete": False,
                "supervisor_iterations": 0,
                "open_source_context": None,
            }
            try:
                final_state = await self.compiled_graph.ainvoke(initial_state)
            except BudgetExceededError as exc:
                span.set_attribute("status", "budget_exceeded")
                return {
                    "workflow_id": workflow_id,
                    "plan": None,
                    "results": {},
                    "final_answer": None,
                    "error": exc.to_response(),
                }
            finally:
                remove_tracker(workflow_id)

            if final_state.get("final_answer"):
                await memory.append("user", user_input)
                await memory.append("assistant", final_state["final_answer"])

            span.set_attribute("status", "success" if not final_state.get("error") else "error")
            return {
                "workflow_id": workflow_id,
                "plan": final_state.get("plan"),
                "results": final_state.get("results"),
                "final_answer": final_state.get("final_answer"),
                "error": final_state.get("error"),
            }

    def _allowed_modules(self, state: AgentState) -> list[ModuleType]:
        configured = state.get("allowed_modules")
        allowed = list(ModuleType) if configured is None else configured
        disabled = set()
        if not self.settings.mcp_enabled:
            disabled.add(ModuleType.MCP)
        if not self.settings.agentscope_enabled:
            disabled.add(ModuleType.AGENTSCOPE)
        if not self.settings.claw_enabled:
            disabled.add(ModuleType.CLAW)
        return [module for module in allowed if module not in disabled]

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
            if agent == ModuleType.MCP and not self.settings.mcp_enabled:
                logger.warning("Skipping MCP task because MCP integration is disabled")
                continue
            if agent == ModuleType.AGENTSCOPE and not self.settings.agentscope_enabled:
                logger.warning(
                    "Skipping AgentScope task because integration is disabled"
                )
                continue
            if agent == ModuleType.CLAW and not self.settings.claw_enabled:
                logger.warning("Skipping Claw task because integration is disabled")
                continue

            schema = task_data.get("expected_output_schema")
            context = task_data.get("context")
            tasks.append(
                Task(
                    id=task_data.get("id") or f"task_{index}_{int(time.time())}",
                    agent=agent,
                    instruction=task_data["instruction"],
                    context=context if isinstance(context, dict) else {},
                    context_from=task_data.get("context_from", []),
                    expected_output_schema=schema if isinstance(schema, dict) else None,
                )
            )
        return tasks

    @staticmethod
    def _merge_context_result(
        context: dict,
        task_id: str,
        output: object,
    ) -> None:
        """Preserve raw upstream output and promote common structured fields."""
        context[task_id] = output
        if not isinstance(output, dict):
            return
        for key, value in output.items():
            context.setdefault(key, value)
        data = output.get("data")
        if isinstance(data, dict):
            for key, value in data.items():
                context.setdefault(key, value)

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

    async def _open_source_context(
        self,
        query: str,
        workflow_id: str = "",
        session_id: str = "",
    ) -> str:
        """Retrieve relevant cloned-repo context for the supervisor prompt."""
        if not self.settings.enable_vector_memory:
            return ""
        if not self.settings.open_source_seed_enabled:
            return ""
        with start_span(
            "rag.open_source_context",
            {
                "workflow_id": workflow_id,
                "session_id": session_id,
                "agent_name": "rag",
            },
        ) as span:
            try:
                memories = await get_long_term_memory().search(
                    query,
                    limit=3,
                    namespace="open_source",
                    score_threshold=0.25,
                )
                span.set_attribute("status", "success")
                span.set_attribute("rag.result_count", len(memories))
            except Exception as exc:
                record_error(span, exc)
                logger.warning("[SUPERVISOR] Open-source context lookup failed: %s", exc)
                return ""

        if not memories:
            return ""

        lines = []
        for memory in memories:
            metadata = memory.get("metadata") or {}
            source_path = (
                metadata.get("source_path") or metadata.get("repo") or "open-source"
            )
            snippet = (memory.get("text") or "").strip().replace("\n", " ")
            if len(snippet) > 900:
                snippet = f"{snippet[:900].rstrip()}..."
            lines.append(f"- {source_path}: {snippet}")

        return "\n".join(lines)


_orchestrator: Optional[MultiAgentOrchestrator] = None


def get_orchestrator() -> MultiAgentOrchestrator:
    """Get or create the process-wide orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MultiAgentOrchestrator()
    return _orchestrator
