"""HTTP client for the central guardrail service."""

from typing import Any, Optional

import httpx

from shared.config import get_settings


class GuardrailServiceError(RuntimeError):
    """Raised when the guardrail service cannot evaluate an operation."""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class GuardrailClient:
    """Fail-closed client for input checks and tool approvals."""

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        settings = get_settings()
        self.base_url = (base_url or settings.guardrail_service_url).rstrip("/")
        self.timeout = timeout or settings.agent_http_timeout_seconds

    async def guard_input(self, prompt: str) -> dict[str, Any]:
        return await self._request("POST", "/guard/input", json={"prompt": prompt})

    async def guard_tool(
        self,
        tool_name: str,
        action: str,
        parameters: Optional[dict[str, Any]] = None,
        approval_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/guard/tool",
            json={
                "tool_name": tool_name,
                "action": action,
                "parameters": parameters or {},
                "approval_id": approval_id,
            },
        )

    async def request_approval(
        self,
        tool_name: str,
        action: str,
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/approvals",
            json={
                "tool_name": tool_name,
                "action": action,
                "parameters": parameters or {},
            },
        )

    async def get_approval(self, approval_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/approvals/{approval_id}")

    async def decide_approval(
        self,
        approval_id: str,
        approved: bool,
        decided_by: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/approvals/{approval_id}/decision",
            json={"approved": approved, "decided_by": decided_by},
        )

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(method, url, json=json)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            try:
                detail = exc.response.json().get("detail", detail)
            except ValueError:
                pass
            raise GuardrailServiceError(str(detail), exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise GuardrailServiceError(f"Guardrail service unavailable: {exc}") from exc

        data = response.json()
        if not isinstance(data, dict):
            raise GuardrailServiceError("Guardrail service returned an invalid response")
        return data
