"""Shared authentication for service-to-service HTTP requests."""

from __future__ import annotations

import secrets
from collections.abc import Iterable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from shared.config import get_settings

INTERNAL_SERVICE_TOKEN_HEADER = "X-Internal-Service-Token"


def get_internal_service_headers() -> dict[str, str]:
    """Return the header required when calling a protected internal service."""
    token = get_settings().internal_service_token.strip()
    return {INTERNAL_SERVICE_TOKEN_HEADER: token} if token else {}


def add_internal_auth_middleware(
    app: FastAPI,
    *,
    public_paths: Iterable[str] = ("/health",),
) -> None:
    """Protect all routes except explicit liveness endpoints."""
    allowed_paths = frozenset(public_paths)

    @app.middleware("http")
    async def require_internal_service_token(request: Request, call_next):
        if request.url.path in allowed_paths:
            return await call_next(request)

        expected = get_settings().internal_service_token.strip()
        provided = request.headers.get(INTERNAL_SERVICE_TOKEN_HEADER, "")
        if not expected:
            return JSONResponse(
                status_code=503,
                content={"detail": "Internal service authentication is not configured"},
            )
        if not secrets.compare_digest(provided, expected):
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid internal service token"},
            )
        return await call_next(request)

