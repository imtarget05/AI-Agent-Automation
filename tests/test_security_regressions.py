import asyncio
from unittest.mock import ANY, AsyncMock, patch

from fastapi.testclient import TestClient

from shared.url_security import validate_outbound_http_url


def test_dashboard_config_does_not_expose_gateway_secret():
    from apps.dashboard.main import app

    response = TestClient(app).get("/config")

    assert response.status_code == 200
    assert "api_key" not in response.json()


def test_internal_tool_service_rejects_missing_token():
    from tools.main import app

    response = TestClient(app).get("/k8s/pods")

    assert response.status_code == 403


def test_internal_tool_service_accepts_configured_token():
    from shared.config import get_settings
    from shared.internal_auth import INTERNAL_SERVICE_TOKEN_HEADER
    from tools.main import app

    response = TestClient(app).get(
        "/k8s/pods",
        headers={
            INTERNAL_SERVICE_TOKEN_HEADER: get_settings().internal_service_token,
        },
    )

    assert response.status_code == 200


def test_outbound_url_validator_rejects_loopback():
    try:
        asyncio.run(validate_outbound_http_url("http://127.0.0.1:8008/health"))
    except ValueError as exc:
        assert "public IP" in str(exc)
    else:
        raise AssertionError("Loopback URL must be rejected")


def test_rag_ingestion_path_stays_under_docs():
    from fastapi import HTTPException
    from services.rag_service.main import _resolve_base_path

    try:
        _resolve_base_path("/app")
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("RAG ingestion outside /app/docs must be rejected")


def test_gateway_forwards_masked_prompt_to_orchestrator():
    from apps.gateway import main as gateway

    orchestrator = AsyncMock()
    orchestrator.execute.return_value = {
        "plan": None,
        "final_answer": "ok",
        "error": None,
    }
    with (
        patch.object(
            gateway.guardrail_client,
            "guard_input",
            new=AsyncMock(
                return_value={
                    "safe": True,
                    "anonymized_prompt": "masked prompt",
                }
            ),
        ),
        patch.object(gateway, "get_orchestrator", return_value=orchestrator),
    ):
        result = asyncio.run(
            gateway.execute_task(
                gateway.TaskRequest(user_input="token=secret-value"),
                api_key="test-key",
            )
        )

    assert result.status == "success"
    orchestrator.execute.assert_awaited_once_with(
        "masked prompt",
        ANY,
        allowed_modules=None,
    )


def test_approved_mutation_can_only_be_claimed_once(tmp_path, monkeypatch):
    from services.approval_service import main as approval_service
    from services.approval_service.store import ApprovalStore
    from shared.config import get_settings
    from shared.internal_auth import INTERNAL_SERVICE_TOKEN_HEADER

    monkeypatch.setattr(
        approval_service,
        "store",
        ApprovalStore(str(tmp_path / "approvals.json")),
    )
    client = TestClient(approval_service.app)
    headers = {
        INTERNAL_SERVICE_TOKEN_HEADER: get_settings().internal_service_token,
    }

    create_response = client.post(
        "/approvals",
        headers=headers,
        json={
            "task_id": "task-1",
            "agent": "k8s",
            "action": "restart_deployment",
            "parameters": {"deployment": "api"},
        },
    )
    assert create_response.status_code == 200
    approval_id = create_response.json()["id"]

    approve_response = client.post(
        f"/approvals/{approval_id}/approve",
        headers=headers,
        json={"decided_by": "operator"},
    )
    assert approve_response.status_code == 200

    first_claim = client.post(
        f"/approvals/{approval_id}/execution/start",
        headers=headers,
    )
    second_claim = client.post(
        f"/approvals/{approval_id}/execution/start",
        headers=headers,
    )

    assert first_claim.status_code == 200
    assert second_claim.status_code == 409
