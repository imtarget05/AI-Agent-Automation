"""
tests/fakes/fake_tools.py — Fake tool implementations for testing
==================================================================
Replaces real Kubernetes / Prometheus / email tools with predictable fakes.
"""

from __future__ import annotations

from typing import Any, Optional


class FakeToolRegistry:
    """Records tool calls and returns canned results.

    Usage::

        registry = FakeToolRegistry()
        registry.register("kubectl_get_pods", result={"pods": ["pod-1"]})
        result = await registry.invoke("kubectl_get_pods", {"namespace": "default"})
    """

    def __init__(self) -> None:
        self._results: dict[str, Any] = {}
        self._errors: dict[str, Exception] = {}
        self._call_log: list[dict[str, Any]] = []

    def register(
        self,
        tool_name: str,
        result: Any = None,
        error: Optional[Exception] = None,
    ) -> "FakeToolRegistry":
        if error is not None:
            self._errors[tool_name] = error
        else:
            self._results[tool_name] = result
        return self

    async def invoke(
        self,
        tool_name: str,
        parameters: Optional[dict[str, Any]] = None,
    ) -> Any:
        self._call_log.append({"tool": tool_name, "params": parameters})
        if tool_name in self._errors:
            raise self._errors[tool_name]
        return self._results.get(
            tool_name,
            {"status": "ok", "tool": tool_name, "fake": True},
        )

    @property
    def call_log(self) -> list[dict[str, Any]]:
        return list(self._call_log)

    def calls_for(self, tool_name: str) -> list[dict[str, Any]]:
        return [c for c in self._call_log if c["tool"] == tool_name]

    def reset(self) -> None:
        self._call_log.clear()


# ──── Pre-built tool fakes ────────────────────────────────────────────────────

def make_k8s_registry(
    *,
    pods: Optional[list[str]] = None,
    deployments: Optional[list[str]] = None,
) -> FakeToolRegistry:
    registry = FakeToolRegistry()
    registry.register(
        "kubectl_get_pods",
        result={"pods": pods or ["payment-service-abc-123"], "namespace": "default"},
    )
    registry.register(
        "kubectl_get_deployments",
        result={"deployments": deployments or ["payment-service"], "namespace": "default"},
    )
    registry.register("kubectl_restart_deployment", result={"status": "restarted"})
    registry.register("kubectl_scale_deployment", result={"status": "scaled"})
    return registry


def make_prometheus_registry(
    *,
    cpu_usage: float = 95.0,
    memory_usage: float = 78.0,
) -> FakeToolRegistry:
    registry = FakeToolRegistry()
    registry.register(
        "prometheus_query",
        result={
            "metrics": [
                {"service": "payment-service", "cpu": cpu_usage, "memory": memory_usage}
            ]
        },
    )
    registry.register(
        "prometheus_range_query",
        result={"data": [{"timestamp": 1717000000, "value": cpu_usage}]},
    )
    return registry
