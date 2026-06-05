"""
shared/observability/tracing.py — OpenTelemetry distributed tracing
====================================================================
Design principles:
  - Fully optional: when OTEL_ENABLED=false (default) the app behaves
    exactly as before. All otel imports are guarded so no hard dependency.
  - One module owns init_tracing(); every other module calls get_tracer().
  - FastAPI middleware is wired by calling instrument_fastapi(app) from
    the gateway lifespan handler.
  - Span helpers (start_span, record_error) work as no-ops when disabled.

Environment variables:
  OTEL_ENABLED                     true | false  (default: false)
  OTEL_SERVICE_NAME                name injected into every span
  OTEL_EXPORTER_OTLP_ENDPOINT      grpc or http/protobuf endpoint
  OTEL_TRACES_EXPORTER             otlp | jaeger | console (default: otlp)
  OTEL_LOG_LEVEL                   INFO | DEBUG

Usage:
  # Once at startup (gateway lifespan):
  from shared.observability.tracing import init_tracing, instrument_fastapi
  init_tracing()
  instrument_fastapi(app)

  # In any agent / service module:
  from shared.observability.tracing import get_tracer, start_span, record_error
  tracer = get_tracer(__name__)
  with start_span("rca.reasoning_step", attributes={"step": 1}) as span:
      ...
      if error:
          record_error(span, exc)
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)

# ──── Feature flag ──────────────────────────────────────────────────────────

_OTEL_ENABLED: bool | None = None  # resolved lazily so tests can patch env


def _is_enabled() -> bool:
    global _OTEL_ENABLED
    if _OTEL_ENABLED is None:
        _OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").strip().lower() == "true"
    return _OTEL_ENABLED


# ──── No-op shims (used when OTEL is disabled) ──────────────────────────────

class _NoOpSpan:
    """Minimal span interface so callers don't need to check for None."""

    def set_attribute(self, key: str, value: Any) -> "_NoOpSpan":  # noqa: ANN001
        return self

    def set_status(self, *args: Any, **kwargs: Any) -> "_NoOpSpan":
        return self

    def record_exception(self, exc: Exception, **kwargs: Any) -> "_NoOpSpan":
        return self

    def add_event(self, name: str, attributes: Optional[dict] = None) -> "_NoOpSpan":
        return self

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoOpTracer:
    def start_as_current_span(self, name: str, **kwargs: Any):  # type: ignore[override]
        return _NoOpSpan()

    def start_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()


_NOOP_TRACER = _NoOpTracer()

# ──── Tracer registry ───────────────────────────────────────────────────────

_tracer_provider = None


def init_tracing(
    service_name: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> None:
    """Initialise the global tracer provider.

    Call once at application startup **after** loading environment variables.
    Safe to call multiple times — subsequent calls are ignored.
    Silently falls back to no-op when OTEL_ENABLED=false or if the optional
    SDK packages are not installed.
    """
    global _tracer_provider, _OTEL_ENABLED
    if enabled is not None:
        _OTEL_ENABLED = enabled

    if _tracer_provider is not None:
        return  # already initialised

    if not _is_enabled():
        logger.debug("[tracing] OTEL_ENABLED=false — tracing disabled")
        return

    try:
        from opentelemetry import trace  # type: ignore[import]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import]
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import]
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME  # type: ignore[import]
    except ImportError:
        logger.warning(
            "[tracing] opentelemetry SDK not installed — tracing disabled. "
            "Install opentelemetry-sdk to enable."
        )
        return

    resolved_name = (
        service_name
        or os.getenv("OTEL_SERVICE_NAME", "ai-agent-automation")
    )
    resource = Resource.create({SERVICE_NAME: resolved_name})
    provider = TracerProvider(resource=resource)

    exporter_type = os.getenv("OTEL_TRACES_EXPORTER", "otlp").lower()
    exporter = _build_exporter(exporter_type)
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    logger.info(
        "[tracing] OpenTelemetry initialised service=%s exporter=%s",
        resolved_name,
        exporter_type,
    )


def _build_exporter(exporter_type: str):  # type: ignore[return]
    """Return the configured span exporter or None on import failure."""
    endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
    )
    try:
        if exporter_type == "console":
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter  # type: ignore[import]
            return ConsoleSpanExporter()

        if exporter_type == "jaeger":
            from opentelemetry.exporter.jaeger.thrift import JaegerExporter  # type: ignore[import]
            return JaegerExporter()

        # Default: OTLP (gRPC)
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import]
                OTLPSpanExporter,
            )
            return OTLPSpanExporter(endpoint=endpoint, insecure=True)
        except ImportError:
            # Fall back to HTTP/protobuf
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import]
                OTLPSpanExporter,
            )
            return OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
    except ImportError as exc:
        logger.warning(
            "[tracing] Could not load exporter %s: %s — spans will be dropped",
            exporter_type,
            exc,
        )
        return None


def get_tracer(name: str = "ai-agent-automation"):
    """Return a tracer for *name*.

    Returns a no-op tracer when OTEL is disabled or not yet initialised.
    """
    if not _is_enabled() or _tracer_provider is None:
        return _NOOP_TRACER

    try:
        return _tracer_provider.get_tracer(name)
    except Exception:
        return _NOOP_TRACER


def instrument_fastapi(app: Any) -> None:
    """Attach OpenTelemetry ASGI middleware to a FastAPI app.

    Must be called *after* init_tracing() and *before* the app starts
    handling requests.
    """
    if not _is_enabled():
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore[import]
        FastAPIInstrumentor.instrument_app(app)
        logger.info("[tracing] FastAPI ASGI instrumented")
    except ImportError:
        logger.warning(
            "[tracing] opentelemetry-instrumentation-fastapi not installed — "
            "HTTP server spans disabled. Install it to enable."
        )


# ──── Context propagation helpers ───────────────────────────────────────────

def get_current_trace_id() -> Optional[str]:
    """Return the hex trace ID of the current span, or None."""
    if not _is_enabled():
        return None
    try:
        from opentelemetry import trace  # type: ignore[import]
        ctx = trace.get_current_span().get_span_context()
        if ctx and ctx.is_valid:
            return format(ctx.trace_id, "032x")
    except Exception:
        pass
    return None


def get_current_span_id() -> Optional[str]:
    """Return the hex span ID of the current span, or None."""
    if not _is_enabled():
        return None
    try:
        from opentelemetry import trace  # type: ignore[import]
        ctx = trace.get_current_span().get_span_context()
        if ctx and ctx.is_valid:
            return format(ctx.span_id, "016x")
    except Exception:
        pass
    return None


def set_span_attributes(span: Any, attributes: Optional[dict[str, Any]]) -> None:
    """Best-effort helper to attach OTEL-safe attributes to a span."""
    if not attributes or not hasattr(span, "set_attribute"):
        return
    for key, value in attributes.items():
        if value is None:
            continue
        try:
            span.set_attribute(str(key), _safe_attr(value))
        except Exception:
            pass


def add_span_event(name: str, attributes: Optional[dict[str, Any]] = None) -> None:
    """Add an event to the current span when tracing is enabled."""
    if not _is_enabled():
        return
    try:
        from opentelemetry import trace  # type: ignore[import]

        span = trace.get_current_span()
        if hasattr(span, "add_event"):
            span.add_event(name, attributes or {})
    except Exception:
        pass


def inject_trace_context() -> dict[str, str]:
    """Return W3C traceparent/tracestate headers for outbound HTTP calls."""
    if not _is_enabled():
        return {}
    try:
        from opentelemetry.propagate import inject  # type: ignore[import]
        carrier: dict[str, str] = {}
        inject(carrier)
        return carrier
    except Exception:
        return {}


# ──── Span context manager ───────────────────────────────────────────────────

@contextmanager
def start_span(
    name: str,
    attributes: Optional[dict[str, Any]] = None,
    tracer_name: str = "ai-agent-automation",
) -> Generator[Any, None, None]:
    """Context manager that creates a child span.

    Usage::

        with start_span("agent.rca", {"agent_name": "rca_agent"}) as span:
            span.set_attribute("step", 1)
            ...

    Works as a no-op when OTEL_ENABLED=false.
    """
    tracer = get_tracer(tracer_name)
    try:
        span = tracer.start_as_current_span(name)
    except Exception:
        span = _NoOpSpan()

    with span as s:
        set_span_attributes(s, attributes)
        yield s


def record_error(span: Any, exc: Exception, reraise: bool = False) -> None:
    """Record an exception on *span* and optionally mark it as error status."""
    try:
        from opentelemetry.trace import StatusCode  # type: ignore[import]
        if hasattr(span, "record_exception"):
            span.record_exception(exc)
        if hasattr(span, "set_status"):
            span.set_status(StatusCode.ERROR, str(exc))
    except Exception:
        if hasattr(span, "record_exception"):
            span.record_exception(exc)
    if reraise:
        raise exc


def _safe_attr(value: Any) -> Any:
    """Coerce value to an OTEL-safe primitive."""
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)
