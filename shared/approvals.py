from typing import Any, Optional, List
import httpx
from shared.config import get_settings


class ApprovalServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class ApprovalClient:
    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        settings = get_settings()
        self.base_url = (base_url or settings.approval_service_url).rstrip("/")
        self.timeout = timeout or settings.agent_http_timeout_seconds

    async def create_approval(
        self,
        task_id: str,
        agent: str,
        action: str,
        parameters: Optional[dict] = None,
        reason: Optional[str] = None,
    ) -> dict:
        return await self._request(
            "POST",
            "/approvals",
            json={
                "task_id": task_id,
                "agent": agent,
                "action": action,
                "parameters": parameters or {},
                "reason": reason,
            },
        )

    async def list_approvals(self) -> List[dict]:
        return await self._request("GET", "/approvals")

    async def get_approval(self, approval_id: str) -> dict:
        return await self._request("GET", f"/approvals/{approval_id}")

    async def approve(self, approval_id: str, decided_by: str) -> dict:
        return await self._request(
            "POST", f"/approvals/{approval_id}/approve", json={"decided_by": decided_by}
        )

    async def reject(self, approval_id: str, decided_by: str) -> dict:
        return await self._request(
            "POST", f"/approvals/{approval_id}/reject", json={"decided_by": decided_by}
        )

    async def record_execution(
        self,
        approval_id: str,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> dict:
        return await self._request(
            "POST",
            f"/approvals/{approval_id}/execution",
            json={
                "status": status,
                "result": result,
                "error": error,
            },
        )

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict] = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(method, url, json=json)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            try:
                detail = exc.response.json().get("detail", detail)
            except ValueError:
                pass
            raise ApprovalServiceError(str(detail), exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise ApprovalServiceError(f"Approval service error: {exc}") from exc
