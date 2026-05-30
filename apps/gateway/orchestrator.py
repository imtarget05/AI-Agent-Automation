"""
LangGraph Orchestrator - Multi-agent workflow
Handles task routing and orchestration between modules
"""
import asyncio
import json
from typing import Optional
from datetime import datetime
import logging
import time
import re

import httpx

from langgraph.graph import StateGraph, END
from langgraph.errors import InvalidImmediateReturnValue

from shared.models import (
    AgentState, ExecutionPlan, Task, TaskResult, TaskStatus, ModuleType
)
from shared.llm import get_llm_router
from shared.memory import get_session_memory, get_long_term_memory
from shared.config import get_settings

logger = logging.getLogger(__name__)


class MultiAgentOrchestrator:
    """Orchestrate workflow between computer use, browser, and social agents"""

    def __init__(self):
        self.llm = get_llm_router()
        self.settings = get_settings()
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build LangGraph workflow"""
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("manager", self._manager_node)
        workflow.add_node("computer_use", self._computer_use_node)
        workflow.add_node("browser", self._browser_node)
        workflow.add_node("social", self._social_node)
        workflow.add_node("synthesize", self._synthesize_node)

        # Set entry point
        workflow.set_entry_point("manager")

        # Add conditional edges (routing logic)
        workflow.add_conditional_edges(
            "manager",
            self._route_tasks,
            {
                "computer_use": "computer_use",
                "browser": "browser",
                "social": "social",
                "synthesize": "synthesize",
            }
        )

        # All agents -> synthesize
        workflow.add_edge("computer_use", "synthesize")
        workflow.add_edge("browser", "synthesize")
        workflow.add_edge("social", "synthesize")

        # End
        workflow.add_edge("synthesize", END)

        return workflow

    async def _manager_node(self, state: AgentState) -> AgentState:
        """
        Manager Agent - analyzes user input and creates execution plan
        """
        logger.info(f"[MANAGER] Processing: {state.user_input}")

        MANAGER_PROMPT = """You are a Task Manager Agent for a multi-module AI system.
        
Your job is to analyze the user's request and create an execution plan by routing to specialized agents:
- COMPUTER_USE: Desktop automation (click UI, fill forms, screenshots, control apps)
- BROWSER: Web browsing (search, scrape, summarize web content)
- SOCIAL: Social media auto-reply (Facebook Fanpage, Zalo OA responses)

## Output Format (MUST BE VALID JSON):
{
    "analysis": "Brief analysis of what needs to be done",
    "tasks": [
        {
            "id": "task_1",
            "agent": "COMPUTER_USE|BROWSER|SOCIAL",
            "instruction": "Detailed instruction for the agent",
            "expected_output_schema": {"type": "object", "fields": ["field1", "field2"]}
        }
    ],
    "estimated_duration_seconds": 30
}

## Few-shot Examples

### Example 1: Browser Task
USER: "Find iPhone 15 prices on Shopee and compare top 3 products"
PLAN: {
    "analysis": "User wants web research - fetch product data from e-commerce site",
    "tasks": [{
        "id": "task_1",
        "agent": "BROWSER",
        "instruction": "Go to shopee.vn/search?q=iphone+15, extract product name, price, and rating for top 3 results",
        "expected_output_schema": {"type": "list", "fields": ["name", "price", "rating", "url"]}
    }]
}

### Example 2: Computer Use Task
USER: "Open Visual Studio Code and create a new file"
PLAN: {
    "analysis": "User needs desktop automation - open app and create file",
    "tasks": [{
        "id": "task_1",
        "agent": "COMPUTER_USE",
        "instruction": "Open VS Code application, create new file, wait for editor to load"
    }]
}

### Example 3: Multi-step Workflow
USER: "Check my Gmail inbox and give me a summary of unread emails"
PLAN: {
    "analysis": "Need to access email via browser automation",
    "tasks": [{
        "id": "task_1",
        "agent": "BROWSER",
        "instruction": "Navigate to gmail.com, read unread emails (at least 5), extract subject and preview",
        "expected_output_schema": {"type": "list", "fields": ["subject", "from", "preview", "timestamp"]}
    }]
}

---

Now analyze this request and create a plan:
"""

        messages = [
            {"role": "system", "content": MANAGER_PROMPT},
            {"role": "user", "content": state.user_input},
        ]

        # Get plan from manager
        response = await self.llm.chat(
            messages=messages,
            task="planning",
            temperature=0.3,
        )

        try:
            # Parse JSON response
            plan_data = json.loads(response)
            
            # Create tasks
            tasks = []
            for task_data in plan_data.get("tasks", []):
                tasks.append(Task(
                    id=task_data["id"],
                    agent=ModuleType(task_data["agent"].lower()),
                    instruction=task_data["instruction"],
                    expected_output_schema=task_data.get("expected_output_schema"),
                ))

            execution_plan = ExecutionPlan(
                user_task=state.user_input,
                tasks=tasks,
                estimated_duration_seconds=plan_data.get("estimated_duration_seconds", 30),
            )

            state["plan"] = execution_plan
            state["messages"].append({"role": "manager", "content": response})

            logger.info(f"[MANAGER] Created plan with {len(tasks)} tasks")

        except json.JSONDecodeError as e:
            logger.error(f"[MANAGER] Failed to parse response: {e}")
            state["error"] = f"Failed to create execution plan: {e}"

        return state

    async def _route_tasks(self, state: AgentState) -> str:
        """Route to appropriate agent based on plan"""
        if not state["plan"] or not state["plan"].tasks:
            return "synthesize"

        # Get first pending task
        for task in state["plan"].tasks:
            if task.id not in state["results"]:
                return task.agent.value

        return "synthesize"

    def _extract_url(self, text: str) -> Optional[str]:
        """Extract first URL from text if present"""
        url_match = re.search(r"https?://\S+", text)
        if url_match:
            return url_match.group(0)

        domain_match = re.search(r"\b([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/\S*)?\b", text)
        if domain_match:
            return f"https://{domain_match.group(0)}"

        return None

    def _extract_fields(self, schema: Optional[dict]) -> Optional[list[str]]:
        """Extract desired fields from expected output schema"""
        if not schema:
            return None
        fields = schema.get("fields")
        if isinstance(fields, list) and all(isinstance(f, str) for f in fields):
            return fields
        return None

    async def _post_agent(self, base_url: str, path: str, payload: dict, timeout: int) -> dict:
        """Send request to agent service"""
        url = f"{base_url}{path}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    async def _computer_use_node(self, state: AgentState) -> AgentState:
        """Computer Use Agent - desktop automation"""
        logger.info("[COMPUTER_USE] Executing...")

        # Find task for this agent
        task = next(
            (t for t in state["plan"].tasks 
             if t.agent == ModuleType.COMPUTER_USE and t.id not in state["results"]),
            None
        )

        if not task:
            return state

        state["current_agent"] = ModuleType.COMPUTER_USE

        start = time.perf_counter()
        try:
            payload = {
                "objective": task.instruction,
            }
            response = await self._post_agent(
                self.settings.computer_use_service_url,
                "/execute",
                payload,
                timeout=task.timeout_seconds or self.settings.agent_http_timeout_seconds,
            )

            status = TaskStatus.COMPLETED if response.get("success") else TaskStatus.FAILED
            result = TaskResult(
                task_id=task.id,
                agent=ModuleType.COMPUTER_USE,
                status=status,
                output=response,
                error_message=response.get("error"),
                execution_time_seconds=time.perf_counter() - start,
            )

            state["results"][task.id] = result
            logger.info(f"[COMPUTER_USE] Task {task.id} completed")

        except Exception as e:
            result = TaskResult(
                task_id=task.id,
                agent=ModuleType.COMPUTER_USE,
                status=TaskStatus.FAILED,
                output=None,
                error_message=str(e),
                execution_time_seconds=time.perf_counter() - start,
            )
            state["results"][task.id] = result
            logger.error(f"[COMPUTER_USE] Task failed: {e}")

        return state

    async def _browser_node(self, state: AgentState) -> AgentState:
        """Browser Agent - web automation"""
        logger.info("[BROWSER] Executing...")

        task = next(
            (t for t in state["plan"].tasks 
             if t.agent == ModuleType.BROWSER and t.id not in state["results"]),
            None
        )

        if not task:
            return state

        state["current_agent"] = ModuleType.BROWSER

        start = time.perf_counter()
        try:
            payload = {
                "instruction": task.instruction,
            }
            url = self._extract_url(task.instruction)
            if url:
                payload["url"] = url

            extract_fields = self._extract_fields(task.expected_output_schema)
            if extract_fields:
                payload["extract_fields"] = extract_fields

            response = await self._post_agent(
                self.settings.browser_service_url,
                "/execute",
                payload,
                timeout=task.timeout_seconds or self.settings.agent_http_timeout_seconds,
            )

            status = TaskStatus.COMPLETED if response.get("success") else TaskStatus.FAILED
            result = TaskResult(
                task_id=task.id,
                agent=ModuleType.BROWSER,
                status=status,
                output=response,
                error_message=response.get("error"),
                execution_time_seconds=time.perf_counter() - start,
            )

            state["results"][task.id] = result
            logger.info(f"[BROWSER] Task {task.id} completed")

        except Exception as e:
            result = TaskResult(
                task_id=task.id,
                agent=ModuleType.BROWSER,
                status=TaskStatus.FAILED,
                output=None,
                error_message=str(e),
                execution_time_seconds=time.perf_counter() - start,
            )
            state["results"][task.id] = result
            logger.error(f"[BROWSER] Task failed: {e}")

        return state

    async def _social_node(self, state: AgentState) -> AgentState:
        """Social Media Agent - FB/Zalo auto-reply"""
        logger.info("[SOCIAL] Executing...")

        task = next(
            (t for t in state["plan"].tasks 
             if t.agent == ModuleType.SOCIAL and t.id not in state["results"]),
            None
        )

        if not task:
            return state

        state["current_agent"] = ModuleType.SOCIAL

        try:
            # Placeholder - actual social media integration
            output = f"[Social] Generated reply: {task.instruction}"
            
            result = TaskResult(
                task_id=task.id,
                agent=ModuleType.SOCIAL,
                status=TaskStatus.COMPLETED,
                output=output,
                execution_time_seconds=2.0,
            )
            
            state["results"][task.id] = result
            logger.info(f"[SOCIAL] Task {task.id} completed")

        except Exception as e:
            result = TaskResult(
                task_id=task.id,
                agent=ModuleType.SOCIAL,
                status=TaskStatus.FAILED,
                output=None,
                error_message=str(e),
                execution_time_seconds=0.0,
            )
            state["results"][task.id] = result
            logger.error(f"[SOCIAL] Task failed: {e}")

        return state

    async def _synthesize_node(self, state: AgentState) -> AgentState:
        """Synthesize results from all agents into final answer"""
        logger.info("[SYNTHESIZER] Creating final answer...")

        # Collect all results
        results_text = "\n".join([
            f"- {r.agent.value}: {r.output}" 
            for r in state["results"].values()
        ])

        SYNTHESIZER_PROMPT = """You are a Result Synthesizer. Combine results from multiple agents into a clear, concise final answer.

User's original request: {user_input}

Results from agents:
{results}

Provide a clear, professional final answer combining all the information above."""

        messages = [
            {
                "role": "system",
                "content": SYNTHESIZER_PROMPT.format(
                    user_input=state["user_input"],
                    results=results_text or "No results to synthesize"
                )
            },
            {"role": "user", "content": "Please synthesize the results above into a final answer"}
        ]

        try:
            response = await self.llm.chat(
                messages=messages,
                task="summarize",
                temperature=0.5,
            )
            state["final_answer"] = response
            state["messages"].append({"role": "synthesizer", "content": response})

        except Exception as e:
            state["error"] = f"Synthesis failed: {e}"
            logger.error(f"[SYNTHESIZER] Error: {e}")

        return state

    async def execute(self, user_input: str, session_id: str) -> dict:
        """Execute the entire workflow"""
        logger.info(f"[ORCHESTRATOR] Starting execution for session {session_id}")

        initial_state = AgentState(
            session_id=session_id,
            user_input=user_input,
            messages=[],
            results={},
        )

        # Run graph
        compiled_graph = self.graph.compile()
        final_state = await asyncio.to_thread(compiled_graph.invoke, initial_state)

        # Save to memory
        session_memory = get_session_memory(session_id)
        await session_memory.append("user", user_input)
        await session_memory.append("assistant", final_state.get("final_answer", ""))

        return {
            "plan": final_state.get("plan"),
            "results": final_state.get("results"),
            "final_answer": final_state.get("final_answer"),
            "error": final_state.get("error"),
        }


# Global instance
_orchestrator: Optional[MultiAgentOrchestrator] = None


def get_orchestrator() -> MultiAgentOrchestrator:
    """Get or create orchestrator instance"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MultiAgentOrchestrator()
    return _orchestrator
