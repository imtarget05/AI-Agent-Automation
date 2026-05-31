#!/usr/bin/env python3
"""
Synthetic Agent Evaluation Fixture CLI.
Evaluates representative fixture outputs against the incident dataset:
- RAG Faithfulness (Faithfulness)
- Answer Relevance (Relevance)
- Agentic Trajectory Correctness (Trajectory)
Prints a comprehensive SRE report card.
"""

import sys
import asyncio
import json
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from services.eval_service.evaluator import AgentEvaluator

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("eval_runner")


async def run_evaluation():
    print("=" * 80)
    print("RUNNING SYNTHETIC AGENT EVALUATION FIXTURES (LLM-AS-A-JUDGE)")
    print("=" * 80)

    # Load dataset
    dataset_path = (
        Path(__file__).resolve().parent.parent / "data" / "evals" / "test_dataset.json"
    )
    if not dataset_path.exists():
        logger.error(f"Test dataset not found at: {dataset_path}")
        return

    with open(dataset_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print(f"Loaded {len(cases)} test cases from dataset.")
    print("-" * 80)

    evaluator = AgentEvaluator()

    # Track statistics
    summary_results = []

    for case in cases:
        print(f"\n🚀 Test Case [{case['id']}] : {case['name']}")
        print(f'   Query: "{case["query"]}"')

        # These are intentionally synthetic fixtures. They exercise the evaluator,
        # not a live remediation pipeline.

        expected_traj = case["expected_trajectory"]

        # High fidelity simulated agent outputs to evaluate faithfulness and relevance
        if case["id"] == "tc_1":
            actual_traj = ["rag", "rca", "devops", "tool"]  # Perfect trajectory
            simulated_answer = (
                "Based on the RAG runbook, CPU spikes above 95% on web-pod-1 scheduled on worker node k8s-node-2 "
                "require an infrastructure patch. The root cause analysis indicates a memory leak in the web application "
                "which triggers high swap usage on k8s-node-2. The proposed remediation is a Kubernetes patch "
                "(CPU limits limits.cpu=2) and a controlled replica-set reschedule onto a healthy node."
            )
        elif case["id"] == "tc_2":
            actual_traj = ["rag", "rca", "email"]  # Perfect trajectory
            simulated_answer = (
                "The authentication service auth-service is experiencing 100% connection timeouts because of a hard dependency "
                "on db-service, which is currently down. Looking at db-pod-0 logs, there are locking issues. The proposed next "
                "step is to draft an incident report email for supervisor@company.com before notifying stakeholders."
            )
        else:
            actual_traj = ["rag", "tool"]  # Perfect trajectory
            simulated_answer = (
                "The Redis caching service (cache-pod-0) is experiencing eviction overload due to the maxmemory-policy. "
                "The caching runbook recommends requesting approval for a controlled cache-pod-0 restart "
                "and verifying whether system latency returns to normal levels."
            )

        print(f"   Trajectory: Expected {expected_traj} | Actual {actual_traj}")

        # Run Judge metrics
        print("   Evaluating groundedness and relevance via LLM-as-a-judge...")
        metrics = await evaluator.run_suite(
            query=case["query"],
            context=case["ground_truth_context"],
            answer=simulated_answer,
            expected_trajectory=expected_traj,
            actual_trajectory=actual_traj,
        )

        print(
            f"   ↳ 🎯 Faithfulness: {metrics['faithfulness']['score']} | Reason: {metrics['faithfulness']['justification']}"
        )
        print(
            f"   ↳ 🎯 Relevance:    {metrics['relevance']['score']} | Reason: {metrics['relevance']['justification']}"
        )
        print(
            f"   ↳ 🎯 Trajectory:   {metrics['trajectory']['score']} | Reason: {metrics['trajectory']['justification']}"
        )
        print(f"   ↳ ⭐ Overall Score: {metrics['overall_accuracy_score']}")

        summary_results.append(
            {
                "id": case["id"],
                "name": case["name"],
                "faithfulness": metrics["faithfulness"]["score"],
                "relevance": metrics["relevance"]["score"],
                "trajectory": metrics["trajectory"]["score"],
                "overall": metrics["overall_accuracy_score"],
                "hallucination": "⚠️ YES"
                if metrics["hallucination_detected"]
                else "✅ NO",
            }
        )

    print("\n" + "=" * 80)
    print("📊 AGENT EVALUATION REPORT CARD SUMMARY")
    print("=" * 80)
    print(
        f"{'ID':<6} | {'Test Case Name':<30} | {'Faithful':<8} | {'Relevance':<9} | {'Traj':<6} | {'Overall':<7} | {'Hallucinate':<11}"
    )
    print("-" * 80)
    for res in summary_results:
        print(
            f"{res['id']:<6} | {res['name']:<30} | {res['faithfulness']:<8.2f} | {res['relevance']:<9.2f} | {res['trajectory']:<6.2f} | {res['overall']:<7.2f} | {res['hallucination']:<11}"
        )
    print("-" * 80)

    avg_overall = sum(r["overall"] for r in summary_results) / len(summary_results)
    print(f"⭐ SYSTEM OVERALL ACCURACY (LLM-AS-A-JUDGE): {avg_overall:.2f} / 1.00")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_evaluation())
