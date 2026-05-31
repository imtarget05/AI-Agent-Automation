"""
Prometheus Tool - queries the Prometheus HTTP API with a stable demo fallback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

import httpx

from shared.config import get_settings

logger = logging.getLogger(__name__)


class PrometheusTool:
    """PromQL instant-query adapter backed by settings.prometheus_url."""

    def __init__(
        self,
        prometheus_url: Optional[str] = None,
        timeout_seconds: float = 5.0,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.prometheus_url = (prometheus_url or get_settings().prometheus_url).rstrip(
            "/"
        )
        self.api_endpoint = f"{self.prometheus_url}/api/v1/query"
        self.timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc).timestamp())

    async def query_metric(
        self,
        query: str,
        time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a PromQL instant query and return the Prometheus response."""
        params = {"query": query}
        if time:
            params["time"] = time

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(self.api_endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Prometheus returned a non-object JSON response")
                logger.info("Fetched Prometheus metrics from %s.", self.prometheus_url)
                return data
        except httpx.HTTPStatusError as exc:
            data = self._json_object_or_none(exc.response)
            if data is not None:
                logger.warning(
                    "Prometheus rejected query with HTTP %s.",
                    exc.response.status_code,
                )
                return data
            logger.warning(
                "Prometheus returned HTTP %s with an invalid response. Using mock fallback.",
                exc.response.status_code,
            )
        except (httpx.RequestError, ValueError) as exc:
            logger.warning(
                "Could not query Prometheus at %s: %s. Using mock fallback.",
                self.prometheus_url,
                exc,
            )

        return self._generate_mock_metric(query)

    @staticmethod
    def _json_object_or_none(response: httpx.Response) -> Optional[Dict[str, Any]]:
        try:
            data = response.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _generate_mock_metric(self, query: str) -> Dict[str, Any]:
        """Generate deterministic demo values for common PromQL query families."""
        now_ts = self._clock()
        query_key = query.lower()
        pod = self._pod_for_query(query_key)

        if "cpu" in query_key:
            value = (
                "0.96"
                if "payment-api" in query_key
                else "0.78"
                if "auth-gateway" in query_key
                else "0.22"
            )
            return self._vector(
                now_ts,
                "container_cpu_usage_seconds_total",
                value,
                {"container": "web-app", "pod": pod},
            )

        if "memory" in query_key or "working_set" in query_key:
            value = (
                "1932735283"
                if "payment-api" in query_key
                else "982736128"
                if "auth-gateway" in query_key
                else "251658240"
            )
            return self._vector(
                now_ts,
                "container_memory_working_set_bytes",
                value,
                {"container": "web-app", "pod": pod},
            )

        if "duration" in query_key or "latency" in query_key:
            value = "4.85" if "payment-api" in query_key else "0.12"
            return self._vector(
                now_ts,
                "http_request_duration_seconds_bucket",
                value,
                {"handler": "/api/v1/payment", "pod": pod},
            )

        return self._vector(
            now_ts,
            "custom_metric",
            "1.0",
            {"pod": pod},
        )

    @staticmethod
    def _pod_for_query(query: str) -> str:
        if "auth-gateway" in query:
            return "auth-gateway-service-84f9b8c2-m4n5"
        if "payment-api" in query:
            return "payment-api-service-7d88c44f-c3d4"
        return "unknown-service"

    @staticmethod
    def _vector(
        timestamp: float,
        metric_name: str,
        value: str,
        labels: Dict[str, str],
    ) -> Dict[str, Any]:
        return {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"__name__": metric_name, **labels},
                        "value": [timestamp, value],
                    }
                ],
            },
        }
