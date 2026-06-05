"""
shared/observability/logging.py — Structured JSON logging with correlation IDs
===============================================================================
Features:
  - JSON log format via python-json-logger
  - Auto-injects trace_id / span_id from OpenTelemetry context when available
  - Auto-injects request_id / workflow_id / agent_name from context vars
  - Single entry point: get_logger(__name__) → drop-in replacement for
    logging.getLogger(__name__)
  - Does NOT log raw secrets or PII

Context variables (set at request boundary, propagated in async context):
  from shared.observability.logging import set_log_context, clear_log_context
  set_log_context(request_id="req-123", workflow_id="wf-456", agent_name="rca")

Usage:
  from shared.observability.logging import get_logger
  logger = get_logger(__name__)
  logger.info("RCA step completed", extra={"step": 2, "duration_ms": 45})
"""

from __future__ import annotations

import logging
import os
import sys
from contextvars import ContextVar
from typing import Optional

# ──── Context variables ─────────────────────────────────────────────────────

_ctx_request_id: ContextVar[str] = ContextVar("request_id", default="")
_ctx_workflow_id: ContextVar[str] = ContextVar("workflow_id", default="")
_ctx_session_id: ContextVar[str] = ContextVar("session_id", default="")
_ctx_tenant_id: ContextVar[str] = ContextVar("tenant_id", default="")
_ctx_user_id: ContextVar[str] = ContextVar("user_id", default="")
_ctx_agent_name: ContextVar[str] = ContextVar("agent_name", default="")
_service_name = os.getenv("OTEL_SERVICE_NAME", "ai-agent-automation")


def set_log_context(
    *,
    request_id: str = "",
    workflow_id: str = "",
    session_id: str = "",
    tenant_id: str = "",
    user_id: str = "",
    agent_name: str = "",
) -> None:
    """Set correlation IDs for the current async task / thread."""
    if request_id:
        _ctx_request_id.set(request_id)
    if workflow_id:
        _ctx_workflow_id.set(workflow_id)
    if session_id:
        _ctx_session_id.set(session_id)
    if tenant_id:
        _ctx_tenant_id.set(tenant_id)
    if user_id:
        _ctx_user_id.set(user_id)
    if agent_name:
        _ctx_agent_name.set(agent_name)


def clear_log_context() -> None:
    """Reset all correlation IDs for the current async task."""
    _ctx_request_id.set("")
    _ctx_workflow_id.set("")
    _ctx_session_id.set("")
    _ctx_tenant_id.set("")
    _ctx_user_id.set("")
    _ctx_agent_name.set("")


def get_log_context() -> dict[str, str]:
    """Return the current correlation context as a plain dict."""
    ctx: dict[str, str] = {}
    if v := _ctx_request_id.get():
        ctx["request_id"] = v
    if v := _ctx_workflow_id.get():
        ctx["workflow_id"] = v
    if v := _ctx_session_id.get():
        ctx["session_id"] = v
    if v := _ctx_tenant_id.get():
        ctx["tenant_id"] = v
    if v := _ctx_user_id.get():
        ctx["user_id"] = v
    if v := _ctx_agent_name.get():
        ctx["agent_name"] = v
    return ctx


# ──── Custom JSON formatter ──────────────────────────────────────────────────

class _CorrelationFilter(logging.Filter):
    """Injects correlation IDs and OTel trace/span IDs into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        # Correlation from context vars
        record.request_id = _ctx_request_id.get() or getattr(record, "request_id", "")
        record.workflow_id = _ctx_workflow_id.get() or getattr(record, "workflow_id", "")
        record.session_id = _ctx_session_id.get() or getattr(record, "session_id", "")
        record.tenant_id = _ctx_tenant_id.get() or getattr(record, "tenant_id", "")
        record.user_id = _ctx_user_id.get() or getattr(record, "user_id", "")
        record.agent_name = _ctx_agent_name.get() or getattr(record, "agent_name", "")
        record.service = getattr(record, "service", _service_name)

        # OpenTelemetry trace context (safe — no hard dependency)
        try:
            from shared.observability.tracing import (
                get_current_trace_id,
                get_current_span_id,
            )
            record.trace_id = get_current_trace_id() or ""
            record.span_id = get_current_span_id() or ""
        except Exception:
            record.trace_id = ""
            record.span_id = ""

        return True


def _build_handler() -> logging.Handler:
    """Return a stderr handler with JSON or plain formatting."""
    handler = logging.StreamHandler(sys.stderr)

    try:
        from pythonjsonlogger import jsonlogger  # type: ignore[import]

        fmt = jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
            " %(service)s %(request_id)s %(workflow_id)s %(session_id)s"
            " %(tenant_id)s %(user_id)s %(agent_name)s"
            " %(trace_id)s %(span_id)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
        handler.setFormatter(fmt)
    except ImportError:
        # Fallback: plain text if python-json-logger not installed
        plain_fmt = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s "
            "[svc=%(service)s req=%(request_id)s wf=%(workflow_id)s trace=%(trace_id)s] "
            "%(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(plain_fmt)

    return handler


# ──── Module-level bootstrap ─────────────────────────────────────────────────

_configured = False
_correlation_filter = _CorrelationFilter()


def configure_logging(
    level: Optional[str] = None,
    service: Optional[str] = None,
) -> None:
    """Configure the root logger once.

    Calling multiple times is safe (subsequent calls are no-ops).
    """
    global _configured, _service_name
    if _configured:
        return

    if service:
        _service_name = service

    resolved_level = level or os.getenv("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, resolved_level, logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove any existing handlers to avoid duplicate output
    root.handlers.clear()

    handler = _build_handler()
    handler.addFilter(_correlation_filter)
    root.addHandler(handler)

    # Add correlation filter to every future logger too
    logging.root.addFilter(_correlation_filter)

    _configured = True

    if service:
        logging.getLogger(__name__).info(
            "Logging configured service=%s level=%s", service, resolved_level
        )


def get_logger(name: str) -> logging.Logger:
    """Drop-in replacement for logging.getLogger(__name__).

    Ensures the root logger is configured and that the returned logger
    participates in correlation-ID injection.
    """
    configure_logging()
    log = logging.getLogger(name)
    # Attach filter directly in case the handler chain differs
    if not any(isinstance(f, _CorrelationFilter) for f in log.filters):
        log.addFilter(_correlation_filter)
    return log
