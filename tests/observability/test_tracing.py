"""
tests/observability/test_tracing.py — OpenTelemetry tracing module tests
=========================================================================
Tests that tracing works correctly in both enabled and disabled modes.
All tests avoid real OTLP connections.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


class TestTracingDisabled:
    """When OTEL_ENABLED=false (default), everything must be a no-op."""

    def setup_method(self):
        # Reset global state between tests
        import shared.observability.tracing as tracing_mod
        tracing_mod._OTEL_ENABLED = None
        tracing_mod._tracer_provider = None

    def test_get_tracer_returns_noop_when_disabled(self):
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            from shared.observability.tracing import get_tracer, _NoOpTracer
            tracer = get_tracer("test")
            assert isinstance(tracer, _NoOpTracer)

    def test_init_tracing_noop_when_disabled(self):
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            from shared.observability.tracing import init_tracing
            init_tracing()
            import shared.observability.tracing as mod
            assert mod._tracer_provider is None

    def test_start_span_noop_does_not_raise(self):
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            from shared.observability.tracing import start_span
            with start_span("test.span", {"key": "value"}) as span:
                assert span is not None  # returns _NoOpSpan

    def test_get_current_trace_id_returns_none(self):
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            from shared.observability.tracing import get_current_trace_id
            assert get_current_trace_id() is None

    def test_inject_trace_context_returns_empty(self):
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            from shared.observability.tracing import inject_trace_context
            headers = inject_trace_context()
            assert headers == {}

    def test_noop_span_supports_all_methods(self):
        from shared.observability.tracing import _NoOpSpan
        span = _NoOpSpan()
        # All methods must be callable and chainable
        span.set_attribute("key", "value")
        span.add_event("my-event", {"a": 1})
        span.set_status("OK")
        span.record_exception(ValueError("boom"))
        with span:
            pass  # context manager support


class TestTracingEnabled:
    """When OTEL_ENABLED=true, verify spans are created via in-memory exporter."""

    def setup_method(self):
        import shared.observability.tracing as tracing_mod
        tracing_mod._OTEL_ENABLED = None
        tracing_mod._tracer_provider = None

    def test_init_tracing_sets_provider(self):
        try:
            import opentelemetry.sdk.trace  # noqa: F401
        except ImportError:
            pytest.skip("opentelemetry-sdk not installed")

        with patch.dict(
            os.environ,
            {
                "OTEL_ENABLED": "true",
                "OTEL_TRACES_EXPORTER": "console",
                "OTEL_SERVICE_NAME": "test-service",
            },
        ):
            from shared.observability import tracing as tracing_mod
            tracing_mod._OTEL_ENABLED = None
            tracing_mod._tracer_provider = None
            tracing_mod.init_tracing()
            assert tracing_mod._tracer_provider is not None

    def test_spans_are_recorded(self):
        try:
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
                InMemorySpanExporter,
            )
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry import trace
        except ImportError:
            pytest.skip("opentelemetry-sdk not installed")

        # Set up a real in-memory provider
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        import shared.observability.tracing as tracing_mod
        tracing_mod._OTEL_ENABLED = True
        tracing_mod._tracer_provider = provider

        with tracing_mod.start_span("test.operation", {"agent": "rca"}) as span:
            span.set_attribute("step", 1)

        spans = exporter.get_finished_spans()
        assert len(spans) >= 1
        span_names = [s.name for s in spans]
        assert "test.operation" in span_names

    def teardown_method(self):
        # Reset OTEL global state
        import shared.observability.tracing as tracing_mod
        tracing_mod._OTEL_ENABLED = None
        tracing_mod._tracer_provider = None
        try:
            from opentelemetry import trace
            from opentelemetry.trace import NoOpTracerProvider
            trace.set_tracer_provider(NoOpTracerProvider())
        except Exception:
            pass


class TestRecordError:
    def test_record_error_on_noop_span_does_not_raise(self):
        from shared.observability.tracing import _NoOpSpan, record_error
        span = _NoOpSpan()
        exc = RuntimeError("test error")
        record_error(span, exc)  # must not raise

    def test_record_error_with_reraise(self):
        from shared.observability.tracing import _NoOpSpan, record_error
        span = _NoOpSpan()
        exc = RuntimeError("reraise me")
        with pytest.raises(RuntimeError, match="reraise me"):
            record_error(span, exc, reraise=True)
