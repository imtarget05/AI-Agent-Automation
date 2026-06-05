"""
Evaluation Service - FastAPI Endpoint for running SRE LLM-as-a-judge tests.
Provides REST interface to verify Agent trajectory, groundedness, and hallucination scores.
"""

import logging
from typing import List
from fastapi import FastAPI, Body, HTTPException
from contextlib import asynccontextmanager

from services.eval_service.evaluator import AgentEvaluator
from shared.internal_auth import add_internal_auth_middleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eval_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🛡️ Starting AIOps Agent Evaluation microservice")
    yield
    logger.info("🛑 Shutting down Evaluation service")


app = FastAPI(
    title="AIOps Evaluation Framework",
    description="Automated LLM-as-a-judge scorer for RAG groundedness and multi-agent trajectories",
    version="1.0.0",
    lifespan=lifespan,
)
add_internal_auth_middleware(app)

evaluator = AgentEvaluator()


@app.get("/health")
def health():
    return {
        "status": "active",
        "service": "eval_service",
        "metrics_supported": [
            "rag_faithfulness",
            "answer_relevance",
            "trajectory_correctness",
        ],
    }


@app.post("/eval/run")
async def run_eval(
    query: str = Body(..., embed=True),
    context: str = Body(..., embed=True),
    answer: str = Body(..., embed=True),
    expected_trajectory: List[str] = Body(..., embed=True),
    actual_trajectory: List[str] = Body(..., embed=True),
):
    """
    Computes SRE metrics for a single agent response.
    """
    try:
        report = await evaluator.run_suite(
            query=query,
            context=context,
            answer=answer,
            expected_trajectory=expected_trajectory,
            actual_trajectory=actual_trajectory,
        )
        return report
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
