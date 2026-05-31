"""
Agent Evaluation Framework (LLM-as-a-judge)
Computes key performance indicators:
1. RAG Faithfulness (is the answer grounded in context?)
2. RAG Answer Relevance (does the answer address the query?)
3. Trajectory Correctness (did the multi-agent execute the expected path?)
"""

import json
import logging
from typing import List, Dict, Any
from shared.llm import get_llm_router

logger = logging.getLogger("evaluator")


class AgentEvaluator:
    def __init__(self):
        self.llm = get_llm_router()

    async def evaluate_faithfulness(
        self, query: str, context: str, answer: str
    ) -> Dict[str, Any]:
        """
        Measures if the agent's final answer is mathematically and logically grounded in the retrieved context.
        Similar to Ragas 'Faithfulness'.
        """
        prompt = f"""You are an independent AI Judge assessing a RAG system.
Evaluate if the final answer is completely grounded in and supported by the retrieved context. Do not use external knowledge.

RAG Context:
{context}

Final Answer:
{answer}

Rate the Faithfulness from 0.0 to 1.0 (where 1.0 means every claim in the answer is backed by the context, and 0.0 means complete hallucination).
Provide your verdict in JSON format:
{{
  "score": 0.9,
  "justification": "Detailed explanation of why this score was given, highlighting any hallucinated statements."
}}
Return only valid JSON. Do not wrap in markdown or backticks."""

        try:
            res = await self.llm.chat(
                [{"role": "user", "content": prompt}], task="summarize", temperature=0.1
            )
            # Simple parser tolerating fenced output
            cleaned = res.replace("```json", "").replace("```", "").strip()
            data = json.loads(cleaned)
            return data
        except Exception as e:
            logger.error(f"Failed to evaluate faithfulness: {e}")
            return {
                "score": 0.0,
                "justification": f"Evaluation failed due to parsing error: {e}",
            }

    async def evaluate_answer_relevance(
        self, query: str, answer: str
    ) -> Dict[str, Any]:
        """
        Measures if the answer directly addresses the original user request.
        Similar to Ragas 'Answer Relevance'.
        """
        prompt = f"""You are an independent AI Judge assessing response relevance.
Evaluate if the generated answer directly, clearly, and comprehensively answers the original user query.

User Query:
{query}

Generated Answer:
{answer}

Rate the Answer Relevance from 0.0 to 1.0 (where 1.0 means perfect alignment, and 0.0 means the answer is completely off-topic).
Provide your verdict in JSON format:
{{
  "score": 0.85,
  "justification": "Detailed explanation of whether the answer missed any parts of the user request."
}}
Return only valid JSON. Do not wrap in markdown or backticks."""

        try:
            res = await self.llm.chat(
                [{"role": "user", "content": prompt}], task="summarize", temperature=0.1
            )
            cleaned = res.replace("```json", "").replace("```", "").strip()
            data = json.loads(cleaned)
            return data
        except Exception as e:
            logger.error(f"Failed to evaluate answer relevance: {e}")
            return {
                "score": 0.0,
                "justification": f"Evaluation failed due to parsing error: {e}",
            }

    async def evaluate_trajectory(
        self, expected_trajectory: List[str], actual_trajectory: List[str]
    ) -> Dict[str, Any]:
        """
        Measures Trajectory Correctness of the LangGraph Multi-Agent execution steps.
        Checks if the agent visited the critical stages required for a correct incident resolution.
        """
        matched = []
        missing = []

        # Check if expected agent types were triggered in sequence/membership
        for agent in expected_trajectory:
            if agent.lower() in [a.lower() for a in actual_trajectory]:
                matched.append(agent)
            else:
                missing.append(agent)

        score = len(matched) / len(expected_trajectory) if expected_trajectory else 1.0

        justification = f"Matched required execution agents: {matched}."
        if missing:
            justification += (
                f" Missing critical execution agents in trajectory: {missing}."
            )
        else:
            justification += " Perfect trajectory execution matches expected DevOps operational flow."

        return {
            "score": score,
            "matched_steps": matched,
            "missing_steps": missing,
            "justification": justification,
        }

    async def run_suite(
        self,
        query: str,
        context: str,
        answer: str,
        expected_trajectory: List[str],
        actual_trajectory: List[str],
    ) -> Dict[str, Any]:
        """Runs the entire suite of LLM-as-a-judge evaluations."""
        faithfulness = await self.evaluate_faithfulness(query, context, answer)
        relevance = await self.evaluate_answer_relevance(query, answer)
        trajectory = await self.evaluate_trajectory(
            expected_trajectory, actual_trajectory
        )

        overall = (
            faithfulness["score"] + relevance["score"] + trajectory["score"]
        ) / 3.0

        return {
            "faithfulness": faithfulness,
            "relevance": relevance,
            "trajectory": trajectory,
            "overall_accuracy_score": round(overall, 2),
            "hallucination_detected": faithfulness["score"] < 0.75,
        }
