"""
Metrics Collection & Storage Module

Tracks system performance, agent efficiency, and cost metrics.
Supports daily and monthly aggregation for analytics.
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MetricType(str, Enum):
    """Types of metrics collected"""

    REQUEST = "request"  # API request
    AGENT_EXECUTION = "agent_execution"  # Agent task
    LLM_CALL = "llm_call"  # LLM API call
    SOCIAL_MESSAGE = "social_message"  # Social bot message
    ERROR = "error"  # System error
    LATENCY = "latency"  # Response time


class AgentType(str, Enum):
    """Types of agents"""

    MANAGER = "manager"
    COMPUTER_USE = "computer_use"
    BROWSER = "browser"
    SOCIAL = "social"
    AIOPS = "aiops"
    RCA = "rca"
    RAG = "rag"
    EMAIL = "email"
    TOOL = "tool"
    GUARDRAIL = "guardrail"
    REPORT = "report"
    DEVOPS = "devops"


class TaskStatus(str, Enum):
    """Task execution status"""

    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


# ─── Pydantic Models ───


class MetricData(BaseModel):
    """Single metric data point"""

    model_config = ConfigDict(use_enum_values=True)

    metric_type: MetricType
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Request metrics
    endpoint: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None

    # Agent metrics
    agent_type: Optional[AgentType] = None
    task_id: Optional[str] = None
    task_status: Optional[TaskStatus] = None
    task_duration_ms: Optional[float] = None

    # LLM metrics
    model_name: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None

    # Social metrics
    platform: Optional[str] = None  # "facebook", "zalo"
    message_type: Optional[str] = None  # "incoming", "outgoing"

    # Error metrics
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    # Custom data
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DailyMetrics(BaseModel):
    """Aggregated daily metrics"""

    date: str  # YYYY-MM-DD

    # Request metrics
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    avg_response_time_ms: float = 0.0

    # Agent metrics
    total_agent_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    avg_task_duration_ms: float = 0.0

    # Agent breakdown
    agent_task_count: Dict[str, int] = Field(default_factory=dict)
    agent_success_rate: Dict[str, float] = Field(default_factory=dict)

    # LLM metrics
    total_llm_calls: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_llm_cost: float = 0.0
    llm_cost_by_model: Dict[str, float] = Field(default_factory=dict)

    # Social metrics
    total_social_messages: int = 0
    facebook_messages: int = 0
    zalo_messages: int = 0

    # Error metrics
    total_errors: int = 0
    error_breakdown: Dict[str, int] = Field(default_factory=dict)

    # Performance
    uptime_percent: float = 100.0
    system_health: str = "healthy"  # "healthy", "degraded", "critical"

    created_at: datetime = Field(default_factory=datetime.utcnow)


class MonthlyMetrics(BaseModel):
    """Aggregated monthly metrics"""

    year_month: str  # YYYY-MM

    # High-level metrics
    total_requests: int = 0
    total_agent_tasks: int = 0
    total_llm_calls: int = 0
    total_messages_processed: int = 0

    # Financial metrics
    total_cost: float = 0.0
    cost_breakdown: Dict[str, float] = Field(default_factory=dict)  # by model
    cost_per_request: float = 0.0

    # Performance metrics
    avg_success_rate: float = 0.0
    avg_response_time_ms: float = 0.0
    avg_agent_task_duration_ms: float = 0.0

    # Reliability
    uptime_percent: float = 0.0
    error_rate: float = 0.0
    error_types: Dict[str, int] = Field(default_factory=dict)

    # Agent efficiency
    agent_efficiency: Dict[str, float] = Field(
        default_factory=dict
    )  # success rate by agent

    # Trends
    daily_metrics: List[DailyMetrics] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=datetime.utcnow)


class SystemHealth(BaseModel):
    """Current system health status"""

    status: str = "healthy"  # "healthy", "degraded", "critical"
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Service status
    gateway_online: bool = True
    social_online: bool = True
    browser_online: bool = True
    computer_use_online: bool = True
    postgres_online: bool = True
    redis_online: bool = True
    qdrant_online: bool = True

    # Resource usage
    memory_percent: float = 0.0
    cpu_percent: float = 0.0
    disk_percent: float = 0.0

    # Recent issues
    recent_errors: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class PerformanceMetrics(BaseModel):
    """Performance comparison metrics"""

    metric_name: str
    current_value: float
    previous_value: float
    change_percent: float  # positive = improvement
    threshold: Optional[float] = None
    status: str  # "good", "warning", "critical"

    benchmark: Optional[str] = None


class EfficiencyScore(BaseModel):
    """Overall efficiency scoring"""

    score: float  # 0-100
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Component scores
    reliability_score: float = 0.0  # Based on success rate
    latency_score: float = 0.0  # Response time
    cost_efficiency_score: float = 0.0  # Cost per request
    resource_utilization_score: float = 0.0  # CPU/Memory

    # Recommendations
    recommendations: List[str] = Field(default_factory=list)

    # Upgrade suggestions
    upgrade_suggestions: List[Dict[str, str]] = Field(default_factory=list)


# ─── Helper Functions ───


def calculate_success_rate(successful: int, total: int) -> float:
    """Calculate success rate percentage"""
    if total == 0:
        return 100.0
    return (successful / total) * 100.0


def calculate_cost_per_request(total_cost: float, total_requests: int) -> float:
    """Calculate average cost per request"""
    if total_requests == 0:
        return 0.0
    return total_cost / total_requests


def get_date_string(date: Optional[datetime] = None) -> str:
    """Get date string in YYYY-MM-DD format"""
    if date is None:
        date = datetime.utcnow()
    return date.strftime("%Y-%m-%d")


def get_month_string(date: Optional[datetime] = None) -> str:
    """Get month string in YYYY-MM format"""
    if date is None:
        date = datetime.utcnow()
    return date.strftime("%Y-%m")


def get_date_range(days: int = 30) -> tuple:
    """Get date range for last N days"""
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    return start, end
