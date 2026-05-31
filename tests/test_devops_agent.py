import asyncio

import pytest
from pydantic import ValidationError

from apps.devops_agent import main as devops_agent


@pytest.mark.parametrize(
    ("action", "parameters"),
    [
        (
            "restart_deployment",
            {"namespace": "prod", "deployment": "payment-api"},
        ),
        (
            "scale_deployment",
            {"namespace": "prod", "deployment": "payment-api", "replicas": 4},
        ),
        (
            "delete_pod",
            {"namespace": "prod", "pod": "payment-api-abc"},
        ),
    ],
)
def test_devops_returns_gateway_compatible_structured_proposal(action, parameters):
    request = devops_agent.TaskRequest(
        instruction=f"Propose {action}",
        action=action,
        parameters=parameters,
    )

    result = asyncio.run(devops_agent.execute_task(request))

    assert result["success"] is True
    assert result["data"]["proposed_action"] == {
        "action": action,
        "parameters": parameters,
    }
    assert result["data"]["approval_endpoint"] == "/self-healing/approvals"
    assert result["data"]["requires_approval"] is True
    assert result["data"]["applied"] is False


def test_devops_rejects_direct_execution_request():
    with pytest.raises(ValidationError):
        devops_agent.TaskRequest(
            instruction="Restart payment API now",
            action="restart_deployment",
            parameters={"namespace": "prod", "deployment": "payment-api"},
            execute=True,
        )


def test_devops_rejects_ambiguous_write_parameters():
    with pytest.raises(ValidationError):
        devops_agent.TaskRequest(
            instruction="Restart payment API",
            action="restart_deployment",
            parameters={
                "namespace": "prod",
                "deployment": "payment-api",
                "pod": "payment-api-abc",
            },
        )


def test_devops_analysis_remains_proposal_only(monkeypatch):
    class FakeLlmRouter:
        async def chat(self, messages, task):
            return "Increase memory limit after review."

    monkeypatch.setattr(devops_agent, "llm_router", FakeLlmRouter())

    result = asyncio.run(
        devops_agent.execute_task(
            devops_agent.TaskRequest(instruction="Analyze payment API OOM")
        )
    )

    assert result["success"] is True
    assert result["data"] == {
        "suggestion": "Increase memory limit after review.",
        "applied": False,
    }
