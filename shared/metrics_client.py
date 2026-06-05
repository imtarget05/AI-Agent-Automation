"""
Metrics Integration Module

Provides utilities for services to send metrics to the monitoring service.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

import httpx

from .metrics import MetricData, MetricType, AgentType, TaskStatus
from .internal_auth import get_internal_service_headers

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Client for sending metrics to monitoring service.

    Usage:
        collector = MetricsCollector("http://localhost:8005")

        # Record a single metric
        await collector.record_request(
            endpoint="/execute",
            status_code=200,
            response_time_ms=123.45
        )

        # Record agent task
        await collector.record_agent_task(
            agent_type="browser",
            task_id="task_123",
            status="success",
            duration_ms=456.78
        )
    """

    def __init__(self, monitoring_url: str = "http://localhost:8005"):
        self.monitoring_url = monitoring_url
        self.client = httpx.AsyncClient(timeout=5.0)

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

    async def record_metric(self, metric: MetricData) -> bool:
        """Record a single metric"""
        try:
            response = await self.client.post(
                f"{self.monitoring_url}/metrics/collect",
                json=metric.model_dump(mode="json"),
                headers=get_internal_service_headers(),
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error recording metric: {e}")
            return False

    async def record_request(
        self,
        endpoint: str,
        method: str = "POST",
        status_code: int = 200,
        response_time_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record API request metric"""
        metric = MetricData(
            metric_type=MetricType.REQUEST,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            response_time_ms=response_time_ms,
            metadata=metadata or {},
        )
        return await self.record_metric(metric)

    async def record_agent_task(
        self,
        agent_type: str,
        task_id: str,
        status: str,
        duration_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record agent task execution"""
        try:
            agent_enum = AgentType(agent_type)
        except ValueError:
            agent_enum = None

        try:
            status_enum = TaskStatus(status)
        except ValueError:
            status_enum = None

        metric = MetricData(
            metric_type=MetricType.AGENT_EXECUTION,
            agent_type=agent_enum,
            task_id=task_id,
            task_status=status_enum,
            task_duration_ms=duration_ms,
            metadata=metadata or {},
        )
        return await self.record_metric(metric)

    async def record_llm_call(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record LLM API call"""
        metric = MetricData(
            metric_type=MetricType.LLM_CALL,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            metadata=metadata or {},
        )
        return await self.record_metric(metric)

    async def record_social_message(
        self,
        platform: str,
        message_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record social media message"""
        metric = MetricData(
            metric_type=MetricType.SOCIAL_MESSAGE,
            platform=platform,
            message_type=message_type,
            metadata=metadata or {},
        )
        return await self.record_metric(metric)

    async def record_error(
        self,
        error_type: str,
        error_message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record system error"""
        metric = MetricData(
            metric_type=MetricType.ERROR,
            error_type=error_type,
            error_message=error_message,
            metadata=metadata or {},
        )
        return await self.record_metric(metric)

    async def batch_record(self, metrics: list) -> bool:
        """Record multiple metrics at once"""
        try:
            response = await self.client.post(
                f"{self.monitoring_url}/metrics/batch",
                json=[m.model_dump(mode="json") for m in metrics],
                headers=get_internal_service_headers(),
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error batch recording: {e}")
            return False


# Global collector instance
_collector: Optional[MetricsCollector] = None


def get_collector(monitoring_url: str = "http://localhost:8005") -> MetricsCollector:
    """Get or create global metrics collector"""
    global _collector
    if _collector is None:
        _collector = MetricsCollector(monitoring_url)
    return _collector


async def close_collector():
    """Close global metrics collector"""
    global _collector
    if _collector is not None:
        await _collector.close()
        _collector = None


# Context manager for timing operations
class TimedOperation:
    """Context manager for timing operations and recording metrics"""

    def __init__(self, collector: MetricsCollector, metric_type: str, **metric_kwargs):
        self.collector = collector
        self.metric_type = metric_type
        self.metric_kwargs = metric_kwargs
        self.start_time = None

    async def __aenter__(self):
        self.start_time = datetime.utcnow()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (datetime.utcnow() - self.start_time).total_seconds() * 1000

        if exc_type is not None:
            # Record error if exception occurred
            await self.collector.record_error(
                error_type=exc_type.__name__, error_message=str(exc_val)
            )
        else:
            # Record success metric
            if self.metric_type == "request":
                await self.collector.record_request(
                    response_time_ms=duration_ms, **self.metric_kwargs
                )
            elif self.metric_type == "agent_task":
                await self.collector.record_agent_task(
                    duration_ms=duration_ms, **self.metric_kwargs
                )
