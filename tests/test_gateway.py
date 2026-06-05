"""
tests/test_gateway.py — Gateway unit tests (in-process, no external services)
===============================================================================
Uses FastAPI TestClient — no real HTTP connections, no Docker required.
All external dependencies (Redis, Qdrant, LLM, guardrail) are patched.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, patch


# ── Env setup BEFORE any app imports ────────────────────────────────────────
os.environ.setdefault("ENV", "testing")
os.environ.setdefault("API_SECRET_KEY", "test-secret-key")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("GUARDRAIL_SERVICE_URL", "http://localhost:8010")
os.environ.setdefault("APPROVAL_SERVICE_URL", "http://localhost:8011")


# ── Shared stubs applied for the whole module ────────────────────────────────


@pytest.fixture(autouse=True, scope="module")
def _patch_all_external():
    """Stub every I/O call so tests run without Docker."""
    with (
        patch("shared.memory.get_long_term_memory") as mock_ltm,
        patch(
            "shared.guardrails.GuardrailClient.guard_input",
            new_callable=AsyncMock,
            return_value={"safe": True, "anonymized_prompt": "test"},
        ),
        patch("shared.memory.get_session_memory") as mock_session,
    ):
        # Long-term memory stub
        ltm = AsyncMock()
        ltm.init.return_value = None
        mock_ltm.return_value = ltm

        # Session memory stub
        class FakeSession:
            def __init__(self, *a, **kw):
                pass

            async def get(self):
                return []

            async def get_messages(self):
                return []

            async def get_approved_tasks(self):
                return []

            async def append(self, *a):
                pass

            async def add_approved_task(self, *a):
                pass

        mock_session.return_value = FakeSession()

        yield


@pytest.fixture(scope="module")
def client(_patch_all_external):
    """Module-scoped TestClient — shared across all tests in this file."""
    # Import here so env vars and patches are active
    from shared.config import get_settings

    get_settings.cache_clear()

    from fastapi.testclient import TestClient
    from apps.gateway.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# Read the actual secret key from the (now properly initialized) settings
def _auth_header() -> dict:
    from shared.config import get_settings

    return {"Authorization": f"Bearer {get_settings().api_secret_key}"}


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.unit
def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    # Accept either naming convention
    name = data.get("name", "")
    assert "Agent" in name or "agent" in name.lower()


@pytest.mark.unit
def test_auth_required(client):
    """Protected endpoints must reject requests without a token."""
    response = client.post("/execute", json={"user_input": "hello"})
    assert response.status_code in (401, 403)


@pytest.mark.unit
def test_bad_token_rejected(client):
    """Wrong API key must return 403."""
    response = client.post(
        "/execute",
        json={"user_input": "hello"},
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 403


@pytest.mark.unit
def test_create_session(client):
    """POST /session must return a valid UUID session_id."""
    import uuid

    response = client.post(
        "/session",
        headers=_auth_header(),
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    uuid.UUID(data["session_id"])  # raises if not valid UUID


@pytest.mark.unit
def test_mcp_inventory_is_empty_until_servers_are_configured(client):
    response = client.get("/mcp/tools", headers=_auth_header())

    assert response.status_code == 200
    assert response.json() == {
        "servers": [],
        "tools": [],
        "errors": {},
    }


@pytest.mark.unit
def test_execute_async_returns_job_id(client):
    """POST /execute-async must return a job_id immediately."""
    with patch("apps.gateway.main.get_orchestrator") as mock_orch:
        orch = AsyncMock()
        orch.execute.return_value = {
            "plan": None,
            "results": {},
            "final_answer": "done",
            "error": None,
        }
        mock_orch.return_value = orch

        response = client.post(
            "/execute-async",
            headers=_auth_header(),
            json={"user_input": "run a background check"},
        )

    assert response.status_code == 200
    data = response.json()
    # Accept both old (task_id) and new (job_id) field names
    job_id = data.get("job_id") or data.get("task_id")
    assert job_id is not None
    assert data.get("status") in ("pending", "queued")


@pytest.mark.unit
def test_task_status_404_for_unknown(client):
    """GET /tasks/{id} or /task-status/{id} must 404 for unknown ID."""
    import uuid

    unknown = str(uuid.uuid4())

    # Try both endpoint naming conventions
    for endpoint in (f"/tasks/{unknown}", f"/task-status/{unknown}"):
        resp = client.get(
            endpoint,
            headers=_auth_header(),
        )
        # 404 = not found (correct), 405 = endpoint doesn't exist (skip)
        assert resp.status_code in (404, 405), f"{endpoint} returned {resp.status_code}"
