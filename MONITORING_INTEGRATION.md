# 🔧 Monitoring Integration Guide

## Quick Start

The monitoring system is already integrated into the Docker Compose setup. Just ensure these services are running:

```bash
docker-compose up -d monitoring dashboard
```

Then access the dashboard at: `http://localhost:8006`

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│  Dashboard (Port 8006)                              │
│  └─> Fetches data from Monitoring API               │
│                                                     │
│  Monitoring Service (Port 8005)                     │
│  ├─> Collects metrics from all services             │
│  ├─> Stores in PostgreSQL                           │
│  ├─> Aggregates daily/monthly reports               │
│  └─> Exposes REST API                               │
│                                                     │
│  Services (8000, 8002, 8003, 8004)                  │
│  └─> Send metrics via HTTP to monitoring service    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 1. Gateway Integration

### Add metrics collection to the gateway:

**File: `apps/gateway/main.py`**

```python
from shared.metrics_client import get_collector

# At startup
collector = get_collector(settings.monitoring_url or "http://localhost:8005")

@app.on_event("shutdown")
async def shutdown():
    from shared.metrics_client import close_collector
    await close_collector()

# Add middleware to track all requests
@app.middleware("http")
async def track_requests(request: Request, call_next):
    start = datetime.utcnow()
    response = await call_next(request)
    duration = (datetime.utcnow() - start).total_seconds() * 1000
    
    await collector.record_request(
        endpoint=request.url.path,
        method=request.method,
        status_code=response.status_code,
        response_time_ms=duration
    )
    return response
```

### Track orchestrator execution:

```python
from shared.metrics_client import get_collector

async def execute_orchestrator(request: ExecuteRequest):
    collector = get_collector()
    
    # Execute task
    plan = await orchestrator.execute(request)
    
    # Record metrics
    await collector.record_agent_task(
        agent_type="manager",
        task_id=request.session_id,
        status="success",
        duration_ms=plan.execution_time_ms
    )
```

---

## 2. LLM Call Tracking

### Track all LLM calls:

**File: `shared/llm.py`**

```python
from shared.metrics_client import get_collector

async def track_llm_call(
    model_name: str,
    response: ChatCompletion,
    cost: float
):
    collector = get_collector()
    await collector.record_llm_call(
        model_name=model_name,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        cost_usd=cost
    )
```

---

## 3. Agent Execution Tracking

### Browser Agent:

```python
from shared.metrics_client import get_collector

async def execute_browser_task(task: BrowserTask):
    collector = get_collector()
    start = datetime.utcnow()
    
    try:
        result = await agent.execute(task)
        duration = (datetime.utcnow() - start).total_seconds() * 1000
        
        await collector.record_agent_task(
            agent_type="browser",
            task_id=task.task_id,
            status="success",
            duration_ms=duration,
            metadata={"url": task.url}
        )
        return result
    except Exception as e:
        await collector.record_error(
            error_type=type(e).__name__,
            error_message=str(e)
        )
        raise
```

### Computer Use Agent:

```python
async def execute_computer_task(task: ComputerTask):
    collector = get_collector()
    start = datetime.utcnow()
    
    try:
        result = await agent.execute(task)
        duration = (datetime.utcnow() - start).total_seconds() * 1000
        
        await collector.record_agent_task(
            agent_type="computer_use",
            task_id=task.task_id,
            status="success",
            duration_ms=duration
        )
        return result
    except Exception as e:
        await collector.record_error(
            error_type=type(e).__name__,
            error_message=str(e)
        )
        raise
```

---

## 4. Social Bot Tracking

### Facebook Integration:

```python
from shared.metrics_client import get_collector

async def handle_facebook_message(message: dict):
    collector = get_collector()
    
    # Record incoming message
    await collector.record_social_message(
        platform="facebook",
        message_type="incoming"
    )
    
    # Process and generate reply
    reply = await generate_reply(message)
    
    # Send reply
    await send_message(reply)
    
    # Record outgoing message
    await collector.record_social_message(
        platform="facebook",
        message_type="outgoing"
    )
```

### Zalo Integration:

```python
async def handle_zalo_message(message: dict):
    collector = get_collector()
    
    # Record incoming message
    await collector.record_social_message(
        platform="zalo",
        message_type="incoming"
    )
    
    # Process and reply...
```

---

## 5. Error Tracking

### Centralized error logging:

```python
from shared.metrics_client import get_collector
import logging

class MetricsHandler(logging.Handler):
    """Logging handler that sends errors to monitoring"""
    
    def __init__(self, collector):
        super().__init__()
        self.collector = collector
    
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            asyncio.create_task(
                self.collector.record_error(
                    error_type=record.name,
                    error_message=record.getMessage()
                )
            )

# Add to logger
handler = MetricsHandler(get_collector())
logging.getLogger().addHandler(handler)
```

---

## 6. Configuration

### Environment variables:

```bash
# .env file
MONITORING_URL=http://monitoring:8005
MONITORING_ENABLED=true
MONITORING_BATCH_SIZE=10          # Batch metrics every N operations
MONITORING_BATCH_TIMEOUT_MS=5000  # Or after 5 seconds
```

### Update `shared/config.py`:

```python
from pydantic import BaseSettings

class Settings(BaseSettings):
    monitoring_url: str = "http://localhost:8005"
    monitoring_enabled: bool = True
    monitoring_batch_size: int = 10
    monitoring_batch_timeout_ms: int = 5000
    
    class Config:
        env_file = ".env"
```

---

## 7. Batch Metrics Collection

For high-volume metrics, use batch collection:

```python
from shared.metrics_client import get_collector, MetricData
from shared.metrics import MetricType

async def batch_record_metrics():
    collector = get_collector()
    metrics = []
    
    # Collect metrics
    for task in completed_tasks:
        metrics.append(MetricData(
            metric_type=MetricType.AGENT_EXECUTION,
            agent_type=task.agent_type,
            task_id=task.id,
            task_status=task.status,
            task_duration_ms=task.duration
        ))
    
    # Send batch
    if metrics:
        await collector.batch_record(metrics)
```

---

## 8. Testing Metrics Integration

### Test metrics collection:

```bash
# Send test metric
curl -X POST http://localhost:8005/metrics/collect \
  -H "Content-Type: application/json" \
  -d '{
    "metric_type": "request",
    "endpoint": "/test",
    "method": "POST",
    "status_code": 200,
    "response_time_ms": 123.45
  }'

# Verify it was recorded
curl http://localhost:8005/metrics/daily/$(date +%Y-%m-%d) | jq
```

### Test dashboard:

```bash
# Open dashboard
open http://localhost:8006

# Should show test metric in Overview tab
```

---

## 9. Monitoring Monitoring

### Health checks:

```bash
# Check monitoring service health
curl http://localhost:8005/health

# Check database
docker-compose exec postgres pg_isready

# Check logs
docker-compose logs -f monitoring
```

### Database queries:

```bash
# Connect to database
docker-compose exec postgres psql -U postgres -d agent_db

# List tables
\dt

# Check metrics
SELECT COUNT(*) FROM metrics;
SELECT COUNT(*) FROM daily_metrics;
SELECT COUNT(*) FROM monthly_metrics;

# View recent metrics
SELECT * FROM metrics ORDER BY timestamp DESC LIMIT 10;
```

---

## 10. Performance Optimization

### Reduce metric overhead:

```python
# Sample metrics (e.g., 10% of requests)
import random

if random.random() < 0.1:  # 10% sampling
    await collector.record_request(...)
```

### Batch async sends:

```python
from asyncio import Queue

class BatchedCollector:
    def __init__(self, batch_size=10):
        self.queue = Queue(maxsize=batch_size)
        self.batch_size = batch_size
    
    async def add_metric(self, metric):
        await self.queue.put(metric)
        if self.queue.qsize() >= self.batch_size:
            await self.flush()
    
    async def flush(self):
        metrics = []
        while not self.queue.empty():
            metrics.append(await self.queue.get())
        if metrics:
            await self.collector.batch_record(metrics)
```

---

## 11. Alerting (Future Enhancement)

```python
# Example: Send alerts when threshold exceeded
async def check_thresholds():
    stats = await get_daily_metrics()
    
    if stats.error_rate > 5:  # Alert if >5% errors
        await send_alert(
            level="warning",
            message=f"Error rate {stats.error_rate}% exceeds threshold"
        )
    
    if stats.avg_response_time_ms > 3000:
        await send_alert(
            level="warning",
            message=f"Response time {stats.avg_response_time_ms}ms is high"
        )
```

---

## Example: Complete Integration

See [gateway/orchestrator.py](../apps/gateway/orchestrator.py) for a complete example of monitoring integration in the orchestrator.

---

## Troubleshooting

### Metrics not appearing in dashboard
1. Check monitoring service is running: `docker-compose ps`
2. Verify PostgreSQL connection
3. Check monitoring service logs: `docker-compose logs monitoring`

### Dashboard slow
1. Check database indexes
2. Reduce metrics collection frequency
3. Clear old metrics: `DELETE FROM metrics WHERE timestamp < NOW() - INTERVAL '30 days'`

### High memory usage
1. Implement metric sampling
2. Archive old metrics
3. Increase aggregation window

---

## Next Steps

1. ✅ Deploy monitoring and dashboard services
2. ✅ Integrate metrics collection in gateway
3. ✅ Add metrics to agent services
4. ✅ Set up dashboards and alerts
5. 📊 Monitor daily/monthly reports
6. 🔧 Optimize based on insights
7. 📈 Scale services as needed

---

**Integration Version**: 1.0.0  
**Last Updated**: May 30, 2026  
**Status**: Ready for Integration ✅
