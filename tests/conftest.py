"""
tests/conftest.py — Root-level pytest configuration
=====================================================
Shared fixtures and auto-skip logic for the entire test suite.

Key behaviour:
  - smoke + production tests: auto-skipped when gateway is not reachable.
    Run them explicitly:  pytest tests/smoke/ -m smoke
  - integration tests: mocked, always runnable without any Docker services.
"""

import os
import socket

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _gateway_reachable() -> bool:
    """Check whether the gateway is accepting connections right now."""
    url = os.getenv(
        "STAGING_GATEWAY_URL",
        os.getenv("PROD_GATEWAY_URL", "http://localhost:8000"),
    )
    # Parse host + port from URL string (no urllib needed)
    url = url.rstrip("/")
    if "://" in url:
        url = url.split("://", 1)[1]
    if ":" in url:
        host, port_str = url.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            port = 80
    else:
        host = url
        port = 80

    return _is_port_open(host, port)


# ─────────────────────────────────────────────────────────────────────────────
# Session-scoped availability check (runs once per pytest session)
# ─────────────────────────────────────────────────────────────────────────────

_GATEWAY_UP: bool | None = None


def _gateway_up() -> bool:
    global _GATEWAY_UP
    if _GATEWAY_UP is None:
        _GATEWAY_UP = _gateway_reachable()
    return _GATEWAY_UP


# ─────────────────────────────────────────────────────────────────────────────
# Auto-skip hook — applied BEFORE any smoke / production test runs
# ─────────────────────────────────────────────────────────────────────────────


def pytest_runtest_setup(item: pytest.Item) -> None:
    """
    Skip smoke and production tests automatically when the gateway is down.

    This prevents 'Connection refused' failures polluting the unit/integration
    test run. Run the smoke suite explicitly once the stack is up:

        make smoke                  # against localhost:8000
        make smoke-staging          # against STAGING_GATEWAY_URL
    """
    marker_names = {m.name for m in item.iter_markers()}

    if "smoke" in marker_names or "production" in marker_names:
        if not _gateway_up():
            gateway_url = os.getenv(
                "STAGING_GATEWAY_URL",
                os.getenv("PROD_GATEWAY_URL", "http://localhost:8000"),
            )
            pytest.skip(
                f"Gateway not reachable at {gateway_url} — "
                "start the stack (make dev) or set STAGING_GATEWAY_URL"
            )
