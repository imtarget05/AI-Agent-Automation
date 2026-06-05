import asyncio
from unittest.mock import AsyncMock


class FakeApprovalClient:
    def __init__(self, approval=None):
        self.approval = approval or {}
        self.created = []
        self.recorded = []
        self.claimed = []

    async def get_approval(self, approval_id):
        return self.approval

    async def create_approval(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "approval-1", "status": "pending", **kwargs}

    async def approve(self, approval_id, decided_by):
        return {
            **self.approval,
            "id": approval_id,
            "status": "approved",
            "decided_by": decided_by,
        }

    async def record_execution(self, approval_id, status, result=None, error=None):
        self.recorded.append(
            {
                "approval_id": approval_id,
                "status": status,
                "result": result,
                "error": error,
            }
        )
        return self.approval

    async def claim_execution(self, approval_id):
        self.claimed.append(approval_id)
        return self.approval


class FakeGuardrails:
    def __init__(self, verdict=None):
        self.verdict = verdict or {
            "verdict": "REQUIRE_APPROVAL",
            "allowed": False,
            "requires_approval": True,
            "reason": "Operator approval required",
        }
        self.calls = []

    async def guard_tool(self, tool_name, action, parameters=None, approval_id=None):
        self.calls.append(
            {
                "tool_name": tool_name,
                "action": action,
                "parameters": parameters,
                "approval_id": approval_id,
            }
        )
        return self.verdict


class FakeK8sTool:
    def __init__(self):
        self.calls = []

    def restart_deployment(self, deployment_name, namespace="default"):
        self.calls.append(
            {
                "action": "restart_deployment",
                "deployment": deployment_name,
                "namespace": namespace,
            }
        )
        return {"status": "restart_requested"}


def test_tool_service_executes_only_exact_approved_callback(monkeypatch):
    from tools import main as tools

    parameters = {"deployment": "payment-api", "namespace": "production"}
    approval_client = FakeApprovalClient(
        {
            "id": "approval-1",
            "status": "approved",
            "action": "restart_deployment",
            "parameters": parameters,
        }
    )
    guardrails = FakeGuardrails()
    k8s = FakeK8sTool()
    monkeypatch.setattr(tools, "approval_client", approval_client)
    monkeypatch.setattr(tools, "guardrail_client", guardrails)
    monkeypatch.setattr(tools, "k8s_tool", k8s)

    result = asyncio.run(
        tools.execute_k8s_write_action(
            tools.K8sWriteActionRequest(
                approval_id="approval-1",
                action="restart_deployment",
                parameters=parameters,
            )
        )
    )

    assert result["success"] is True
    assert k8s.calls == [
        {
            "action": "restart_deployment",
            "deployment": "payment-api",
            "namespace": "production",
        }
    ]
    assert guardrails.calls[0]["action"] == "restart_deployment"
    assert approval_client.claimed == ["approval-1"]


def test_gateway_creates_durable_self_healing_approval(monkeypatch):
    from apps.gateway import main as gateway

    approvals = FakeApprovalClient()
    guardrails = FakeGuardrails()
    monkeypatch.setattr(gateway, "approval_client", approvals)
    monkeypatch.setattr(gateway, "guardrail_client", guardrails)

    result = asyncio.run(
        gateway.create_self_healing_approval(
            gateway.SelfHealingApprovalRequest(
                task_id="task-1",
                action="delete_pod",
                parameters={"pod": "payment-api-123", "namespace": "production"},
            ),
            api_key="test-key",
        )
    )

    assert result["requires_approval"] is True
    assert result["approval"]["id"] == "approval-1"
    assert approvals.created[0]["task_id"] == "task-1"
    assert approvals.created[0]["agent"] == "k8s"


def test_gateway_approve_dispatches_callback(monkeypatch):
    from apps.gateway import main as gateway

    approvals = FakeApprovalClient(
        {
            "id": "approval-1",
            "action": "scale_deployment",
            "parameters": {"deployment": "worker", "replicas": 3},
        }
    )
    execute_callback = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(gateway, "approval_client", approvals)
    monkeypatch.setattr(
        gateway, "_execute_approved_self_healing_action", execute_callback
    )

    result = asyncio.run(
        gateway.approve_self_healing_action(
            approval_id="approval-1",
            decision=gateway.SelfHealingApprovalDecision(decided_by="sre@example.com"),
            api_key="test-key",
        )
    )

    assert result["execution"] == {"success": True}
    execute_callback.assert_awaited_once()
    assert result["approval"]["decided_by"] == "sre@example.com"
