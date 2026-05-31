"""
Monitoring Service - Metrics Collection & Storage

Provides REST API for collecting and querying system metrics.
Aggregates data for daily/monthly reports.
"""

from datetime import datetime, timedelta
from typing import List
import logging

from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import json

from shared.config import get_settings
from shared.metrics import (
    MetricData,
    DailyMetrics,
    MonthlyMetrics,
    SystemHealth,
    EfficiencyScore,
    get_date_string,
    calculate_success_rate,
    calculate_cost_per_request,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Database setup
DATABASE_URL = settings.monitoring_database_url
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ─── Database Models ───


class MetricRecord(Base):
    """Database model for individual metrics"""

    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    metric_type = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # Metric-specific fields
    endpoint = Column(String, nullable=True)
    method = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    response_time_ms = Column(Float, nullable=True)

    agent_type = Column(String, nullable=True)
    task_id = Column(String, nullable=True, index=True)
    task_status = Column(String, nullable=True)
    task_duration_ms = Column(Float, nullable=True)

    model_name = Column(String, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)

    platform = Column(String, nullable=True)
    message_type = Column(String, nullable=True)

    error_type = Column(String, nullable=True)
    error_message = Column(String, nullable=True)

    metric_metadata = Column("metadata", JSON, nullable=True)


class DailyMetricRecord(Base):
    """Database model for daily aggregated metrics"""

    __tablename__ = "daily_metrics"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, unique=True, index=True)
    data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


class MonthlyMetricRecord(Base):
    """Database model for monthly aggregated metrics"""

    __tablename__ = "monthly_metrics"

    id = Column(Integer, primary_key=True, index=True)
    year_month = Column(String, unique=True, index=True)
    data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


# Create tables
Base.metadata.create_all(bind=engine)

# ─── FastAPI App ───

app = FastAPI(
    title="Monitoring Service",
    description="System metrics collection and analytics",
    version="1.0.0",
)

# ─── Dependencies ───


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _enum_value(value):
    """Return a stable database value for enums and enum-like strings."""
    return value.value if hasattr(value, "value") else value


def _to_metric_record(metric: MetricData) -> MetricRecord:
    """Map API metrics to the persistence model in one place."""
    return MetricRecord(
        metric_type=_enum_value(metric.metric_type),
        timestamp=metric.timestamp,
        endpoint=metric.endpoint,
        method=metric.method,
        status_code=metric.status_code,
        response_time_ms=metric.response_time_ms,
        agent_type=_enum_value(metric.agent_type),
        task_id=metric.task_id,
        task_status=_enum_value(metric.task_status),
        task_duration_ms=metric.task_duration_ms,
        model_name=metric.model_name,
        input_tokens=metric.input_tokens,
        output_tokens=metric.output_tokens,
        cost_usd=metric.cost_usd,
        platform=metric.platform,
        message_type=metric.message_type,
        error_type=metric.error_type,
        error_message=metric.error_message,
        metric_metadata=metric.metadata,
    )


def _json_object(data):
    """Read JSON columns and tolerate legacy string payloads."""
    return json.loads(data) if isinstance(data, str) else data


# ─── Metrics Collection Routes ───


@app.post("/metrics/collect", tags=["Metrics"])
async def collect_metric(metric: MetricData, db: Session = Depends(get_db)):
    """
    Collect a single metric data point.

    This endpoint receives metrics from various services and stores them
    for analysis and aggregation.
    """
    try:
        record = _to_metric_record(metric)
        db.add(record)
        db.commit()
        logger.info(f"Collected metric: {metric.metric_type}")
        return {"status": "success", "message": "Metric recorded"}
    except Exception as e:
        logger.error(f"Error collecting metric: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/metrics/batch", tags=["Metrics"])
async def collect_metrics_batch(
    metrics: List[MetricData], db: Session = Depends(get_db)
):
    """Batch collect multiple metrics"""
    try:
        for metric in metrics:
            db.add(_to_metric_record(metric))
        db.commit()
        logger.info(f"Batch recorded {len(metrics)} metrics")
        return {"status": "success", "count": len(metrics)}
    except Exception as e:
        logger.error(f"Error batch recording: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Metrics Aggregation Routes ───


@app.get("/metrics/daily/{date}", response_model=DailyMetrics, tags=["Analytics"])
async def get_daily_metrics(date: str, db: Session = Depends(get_db)):
    """
    Get aggregated daily metrics for a specific date (YYYY-MM-DD format).

    Returns comprehensive daily statistics including request counts,
    success rates, performance metrics, and costs.
    """
    try:
        # Check if cached
        cached = db.query(DailyMetricRecord).filter_by(date=date).first()
        if cached:
            return DailyMetrics(**_json_object(cached.data))

        # Calculate from raw metrics
        start = datetime.strptime(date, "%Y-%m-%d")
        end = start + timedelta(days=1)

        metrics = (
            db.query(MetricRecord)
            .filter(MetricRecord.timestamp >= start, MetricRecord.timestamp < end)
            .all()
        )

        if not metrics:
            return DailyMetrics(date=date)

        # Aggregate
        daily = DailyMetrics(date=date)

        for metric in metrics:
            if metric.metric_type == "request":
                daily.total_requests += 1
                if metric.status_code and metric.status_code < 400:
                    daily.successful_requests += 1
                else:
                    daily.failed_requests += 1
                if metric.response_time_ms:
                    daily.avg_response_time_ms = (
                        daily.avg_response_time_ms * (daily.total_requests - 1)
                        + metric.response_time_ms
                    ) / daily.total_requests

            elif metric.metric_type == "agent_execution":
                daily.total_agent_tasks += 1
                if metric.agent_type:
                    daily.agent_task_count[metric.agent_type] = (
                        daily.agent_task_count.get(metric.agent_type, 0) + 1
                    )
                if metric.task_status == "success":
                    daily.successful_tasks += 1
                elif metric.task_status == "failed":
                    daily.failed_tasks += 1
                if metric.task_duration_ms:
                    daily.avg_task_duration_ms = (
                        daily.avg_task_duration_ms * (daily.total_agent_tasks - 1)
                        + metric.task_duration_ms
                    ) / daily.total_agent_tasks

            elif metric.metric_type == "llm_call":
                daily.total_llm_calls += 1
                if metric.input_tokens:
                    daily.input_tokens += metric.input_tokens
                if metric.output_tokens:
                    daily.output_tokens += metric.output_tokens
                daily.total_tokens += (metric.input_tokens or 0) + (
                    metric.output_tokens or 0
                )
                if metric.cost_usd:
                    daily.total_llm_cost += metric.cost_usd
                    if metric.model_name:
                        daily.llm_cost_by_model[metric.model_name] = (
                            daily.llm_cost_by_model.get(metric.model_name, 0)
                            + metric.cost_usd
                        )

            elif metric.metric_type == "social_message":
                daily.total_social_messages += 1
                if metric.platform == "facebook":
                    daily.facebook_messages += 1
                elif metric.platform == "zalo":
                    daily.zalo_messages += 1

            elif metric.metric_type == "error":
                daily.total_errors += 1
                if metric.error_type:
                    daily.error_breakdown[metric.error_type] = (
                        daily.error_breakdown.get(metric.error_type, 0) + 1
                    )

        # Calculate success rates
        for agent, count in daily.agent_task_count.items():
            agent_tasks = [
                m
                for m in metrics
                if m.agent_type == agent and m.metric_type == "agent_execution"
            ]
            agent_successful = len(
                [m for m in agent_tasks if m.task_status == "success"]
            )
            daily.agent_success_rate[agent] = calculate_success_rate(
                agent_successful, count
            )

        # Cache the result
        record = DailyMetricRecord(date=date, data=daily.model_dump(mode="json"))
        db.merge(record)
        db.commit()

        return daily
    except Exception as e:
        logger.error(f"Error calculating daily metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/metrics/monthly/{year_month}", response_model=MonthlyMetrics, tags=["Analytics"]
)
async def get_monthly_metrics(year_month: str, db: Session = Depends(get_db)):
    """
    Get aggregated monthly metrics for a specific month (YYYY-MM format).

    Returns comprehensive monthly statistics, trends, and cost analysis.
    Includes daily breakdowns for the entire month.
    """
    try:
        # Check cache
        cached = db.query(MonthlyMetricRecord).filter_by(year_month=year_month).first()
        if cached:
            return MonthlyMetrics(**_json_object(cached.data))

        # Get all days in month
        year, month = year_month.split("-")
        year, month = int(year), int(month)

        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)

        monthly = MonthlyMetrics(year_month=year_month)

        # Get daily metrics for aggregation
        current = start
        while current < end:
            date_str = get_date_string(current)
            daily = await get_daily_metrics(date_str, db)
            monthly.daily_metrics.append(daily)

            monthly.total_requests += daily.total_requests
            monthly.total_agent_tasks += daily.total_agent_tasks
            monthly.total_llm_calls += daily.total_llm_calls
            monthly.total_messages_processed += daily.total_social_messages
            monthly.total_cost += daily.total_llm_cost

            current += timedelta(days=1)

        # Calculate aggregates
        if monthly.total_requests > 0:
            monthly.cost_per_request = calculate_cost_per_request(
                monthly.total_cost, monthly.total_requests
            )

        # Average metrics
        if len(monthly.daily_metrics) > 0:
            monthly.avg_response_time_ms = sum(
                d.avg_response_time_ms for d in monthly.daily_metrics
            ) / len(monthly.daily_metrics)
            monthly.avg_agent_task_duration_ms = sum(
                d.avg_task_duration_ms for d in monthly.daily_metrics
            ) / len(monthly.daily_metrics)

            if monthly.total_requests > 0:
                monthly.avg_success_rate = (
                    (
                        monthly.total_requests
                        - sum(d.failed_requests for d in monthly.daily_metrics)
                    )
                    / monthly.total_requests
                    * 100
                )

            monthly.error_rate = (
                sum(d.total_errors for d in monthly.daily_metrics)
                / max(monthly.total_requests, 1)
            ) * 100

            # Error breakdown
            for daily in monthly.daily_metrics:
                for error_type, count in daily.error_breakdown.items():
                    monthly.error_types[error_type] = (
                        monthly.error_types.get(error_type, 0) + count
                    )

        # Cost breakdown
        all_models = set()
        for daily in monthly.daily_metrics:
            all_models.update(daily.llm_cost_by_model.keys())
        for model in all_models:
            total_model_cost = sum(
                d.llm_cost_by_model.get(model, 0) for d in monthly.daily_metrics
            )
            monthly.cost_breakdown[model] = total_model_cost

        # Agent efficiency
        all_agents = set()
        for daily in monthly.daily_metrics:
            all_agents.update(daily.agent_success_rate.keys())
        for agent in all_agents:
            rates = [
                d.agent_success_rate.get(agent, 0)
                for d in monthly.daily_metrics
                if agent in d.agent_success_rate
            ]
            if rates:
                monthly.agent_efficiency[agent] = sum(rates) / len(rates)

        # Cache
        record = MonthlyMetricRecord(
            year_month=year_month, data=monthly.model_dump(mode="json")
        )
        db.merge(record)
        db.commit()

        return monthly
    except Exception as e:
        logger.error(f"Error calculating monthly metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics/current-health", response_model=SystemHealth, tags=["Health"])
async def get_system_health(db: Session = Depends(get_db)):
    """Get current system health status"""
    try:
        health = SystemHealth()

        # Check recent errors (last 1 hour)
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        recent_errors = (
            db.query(MetricRecord)
            .filter(
                MetricRecord.metric_type == "error",
                MetricRecord.timestamp >= one_hour_ago,
            )
            .limit(10)
            .all()
        )

        for error in recent_errors:
            health.recent_errors.append(
                {
                    "type": error.error_type,
                    "message": error.error_message,
                    "timestamp": error.timestamp.isoformat(),
                }
            )

        # Determine overall status
        if len(health.recent_errors) > 5:
            health.status = "critical"
        elif len(health.recent_errors) > 2:
            health.status = "degraded"
        else:
            health.status = "healthy"

        return health
    except Exception as e:
        logger.error(f"Error getting health: {e}")
        return SystemHealth(status="unknown")


@app.get(
    "/metrics/efficiency-score", response_model=EfficiencyScore, tags=["Analytics"]
)
async def get_efficiency_score(days: int = 7, db: Session = Depends(get_db)):
    """
    Calculate overall efficiency score based on recent performance.

    Score breakdown:
    - Reliability (0-25): Success rate
    - Latency (0-25): Response time performance
    - Cost Efficiency (0-25): Cost per request
    - Resource (0-25): Resource utilization
    """
    try:
        end = datetime.utcnow()
        start = end - timedelta(days=days)

        metrics = (
            db.query(MetricRecord)
            .filter(MetricRecord.timestamp >= start, MetricRecord.timestamp <= end)
            .all()
        )

        if not metrics:
            return EfficiencyScore(score=0)

        # Calculate component scores
        requests = [m for m in metrics if m.metric_type == "request"]
        tasks = [m for m in metrics if m.metric_type == "agent_execution"]
        llm_calls = [m for m in metrics if m.metric_type == "llm_call"]

        # Reliability score
        if tasks:
            success_count = len([m for m in tasks if m.task_status == "success"])
            reliability_score = (success_count / len(tasks)) * 25
        else:
            reliability_score = 25

        # Latency score (target: <2000ms)
        if requests:
            avg_latency = sum(
                m.response_time_ms for m in requests if m.response_time_ms
            ) / max(len(requests), 1)
            latency_score = max(0, 25 * (2000 - avg_latency) / 2000)
        else:
            latency_score = 25

        # Cost efficiency (target: <$0.01 per request)
        if requests and llm_calls:
            total_cost = sum(m.cost_usd for m in llm_calls if m.cost_usd)
            cost_per_req = total_cost / len(requests)
            cost_efficiency_score = (
                max(0, 25 * (0.01 - cost_per_req) / 0.01) if cost_per_req < 0.01 else 0
            )
            cost_efficiency_score = min(25, max(0, 25 - (cost_per_req * 2500)))
        else:
            cost_efficiency_score = 25

        # Resource (placeholder - would need system metrics)
        resource_utilization_score = 20

        total_score = (
            reliability_score
            + latency_score
            + cost_efficiency_score
            + resource_utilization_score
        )

        score = EfficiencyScore(
            score=total_score,
            reliability_score=reliability_score,
            latency_score=latency_score,
            cost_efficiency_score=cost_efficiency_score,
            resource_utilization_score=resource_utilization_score,
        )

        # Add recommendations
        if reliability_score < 20:
            score.recommendations.append(
                "Improve task reliability - focus on error handling"
            )
        if latency_score < 20:
            score.recommendations.append(
                "Optimize response times - consider caching strategies"
            )
        if cost_efficiency_score < 20:
            score.recommendations.append(
                "Review LLM usage patterns - consider cheaper models for simple tasks"
            )

        # Upgrade suggestions
        if reliability_score < 18:
            score.upgrade_suggestions.append(
                {
                    "area": "reliability",
                    "suggestion": "Implement retry logic and circuit breakers",
                    "priority": "high",
                }
            )

        return score
    except Exception as e:
        logger.error(f"Error calculating efficiency score: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "service": "monitoring"}


if __name__ == "__main__":
    import uvicorn
    from shared.config import get_bind_host

    uvicorn.run(app, host=get_bind_host(), port=8005)
