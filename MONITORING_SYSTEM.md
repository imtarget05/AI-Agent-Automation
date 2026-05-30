# 🎯 Monitoring System - Complete Guide

## Overview

The AI Agent Platform includes a **comprehensive real-time monitoring system** that tracks performance, efficiency, and costs across all components.

**Components:**
1. **Monitoring Service** (Port 8005) - Metrics collection & aggregation
2. **Dashboard** (Port 8006) - Web-based visualization
3. **Metrics Client** - Library for services to send metrics
4. **Database** - PostgreSQL storage for metrics

---

## 🚀 Quick Start

### 1. Start Services

```bash
# Start all services including monitoring
docker-compose up -d

# Verify they're running
docker-compose ps | grep -E "monitoring|dashboard"
```

### 2. Access Dashboard

```bash
# Open in browser
http://localhost:8006

# Or via ngrok (if using tunnel)
https://your-ngrok-url/
```

### 3. Test Metrics Collection

```bash
# Send a test metric
curl -X POST http://localhost:8005/metrics/collect \
  -H "Content-Type: application/json" \
  -d '{
    "metric_type": "request",
    "endpoint": "/test",
    "status_code": 200,
    "response_time_ms": 100
  }'

# Verify it appears in dashboard
# Reload http://localhost:8006 and check the metrics
```

---

## 📊 Dashboard Features

### Overview Tab (Default)
Real-time system status with KPIs:
- Total requests (7-day)
- Success rate
- Average response time
- Total cost
- Efficiency score
- System health

**Charts:**
- Request trends
- Agent performance
- Cost breakdown

### Daily Analytics Tab
Detailed metrics for a specific day:
- Daily requests, tasks, errors
- Success rates
- Response times
- Daily costs

### Monthly Report Tab
Long-term trends and analysis:
- Monthly totals
- Cost analysis
- Reliability metrics
- Daily breakdown

### Performance Tab
Efficiency scoring and optimization:
- Overall score (0-100)
- Component scores
- Recommendations
- Trends

### Cost Analysis Tab
Financial metrics and optimization:
- Total costs by model
- Cost per request
- Optimization suggestions

---

## 🔄 Data Flow

```
Service              Metrics Client       Monitoring Service      Dashboard
  │                       │                       │                  │
  ├─ execute task ────────┤                       │                  │
  │                       │                       │                  │
  │                       ├─ POST /collect ─────>│                  │
  │                       │                       │                  │
  │                       │                       ├─ Store in DB     │
  │                       │                       │                  │
  │                       │                       ├─ Aggregate       │
  │                       │                       │                  │
  │                       │                       │<─ GET /daily ────┤
  │                       │                       │<─ GET /monthly ──┤
  │                       │                       │<─ GET /score ────┤
  │                       │                       │                  │
  │                       │                       │                  ├─ Render graphs
  │                       │                       │                  ├─ Show alerts
  │                       │                       │                  └─ Update cards
```

---

## 📈 Metrics Types

### Request Metrics
```json
{
  "metric_type": "request",
  "endpoint": "/execute",
  "method": "POST",
  "status_code": 200,
  "response_time_ms": 123.45
}
```

### Agent Task Metrics
```json
{
  "metric_type": "agent_execution",
  "agent_type": "browser",
  "task_id": "task_123",
  "task_status": "success",
  "task_duration_ms": 456.78
}
```

### LLM Call Metrics
```json
{
  "metric_type": "llm_call",
  "model_name": "gpt-4o",
  "input_tokens": 100,
  "output_tokens": 50,
  "cost_usd": 0.003
}
```

### Social Message Metrics
```json
{
  "metric_type": "social_message",
  "platform": "facebook",
  "message_type": "incoming"
}
```

### Error Metrics
```json
{
  "metric_type": "error",
  "error_type": "TimeoutError",
  "error_message": "Request timed out after 30s"
}
```

---

## 🔌 Integration Examples

### Python FastAPI Service

```python
from fastapi import FastAPI
from shared.metrics_client import get_collector

app = FastAPI()
collector = get_collector("http://localhost:8005")

@app.post("/execute")
async def execute(request: ExecuteRequest):
    start = datetime.utcnow()
    
    try:
        # Do work
        result = await process(request)
        duration = (datetime.utcnow() - start).total_seconds() * 1000
        
        # Record success
        await collector.record_agent_task(
            agent_type="browser",
            task_id=request.task_id,
            status="success",
            duration_ms=duration
        )
        return result
    
    except Exception as e:
        # Record error
        await collector.record_error(
            error_type=type(e).__name__,
            error_message=str(e)
        )
        raise

@app.on_event("shutdown")
async def shutdown():
    from shared.metrics_client import close_collector
    await close_collector()
```

### FastAPI Middleware

```python
from fastapi import Request
from shared.metrics_client import get_collector

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    collector = get_collector()
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

### LLM Call Tracking

```python
from shared.llm import LLMRouter
from shared.metrics_client import get_collector

router = LLMRouter()
collector = get_collector()

async def call_llm(prompt: str, model: str):
    response = await router.chat(prompt, model)
    
    # Calculate cost
    cost = calculate_cost(model, response.usage)
    
    # Record metric
    await collector.record_llm_call(
        model_name=model,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        cost_usd=cost
    )
    
    return response
```

---

## 📊 Key Metrics

### Success Rate
```
Success Rate = (Successful Tasks / Total Tasks) × 100
```
**Target:** ≥ 98%

### Average Response Time
Mean time for request completion.
**Target:** < 2,000 ms

### Cost Per Request
```
Cost Per Request = Total LLM Cost / Total Requests
```
**Target:** < $0.01

### Efficiency Score
Composite score combining:
- Reliability (success rate): 0-25 points
- Latency (response time): 0-25 points
- Cost Efficiency: 0-25 points
- Resource Utilization: 0-25 points

**Total:** 0-100 points

**Interpretation:**
- 75-100: Excellent
- 50-74: Good
- 25-49: Needs improvement
- 0-24: Critical

---

## 🎯 Setting Optimization Goals

### Reduce Costs
1. Monitor cost by model in dashboard
2. Identify expensive models
3. Use gpt-4o-mini for simple tasks
4. Batch requests to reduce overhead

**Target:** < $0.005 per request

### Improve Reliability
1. Monitor error rate trend
2. Identify most common errors
3. Implement retry logic
4. Add circuit breakers

**Target:** > 98% success rate

### Optimize Performance
1. Monitor response time distribution
2. Identify slow endpoints
3. Add caching
4. Optimize database queries

**Target:** < 500 ms average

---

## 🗄️ Database Schema

### Metrics Table
```sql
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY,
    metric_type VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP DEFAULT NOW(),
    
    -- Request metrics
    endpoint VARCHAR(255),
    method VARCHAR(10),
    status_code INTEGER,
    response_time_ms FLOAT,
    
    -- Agent metrics
    agent_type VARCHAR(50),
    task_id VARCHAR(255),
    task_status VARCHAR(50),
    task_duration_ms FLOAT,
    
    -- LLM metrics
    model_name VARCHAR(100),
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd FLOAT,
    
    -- Social metrics
    platform VARCHAR(50),
    message_type VARCHAR(50),
    
    -- Error metrics
    error_type VARCHAR(100),
    error_message TEXT,
    
    -- Custom data
    metadata JSONB
);

CREATE INDEX idx_metrics_type ON metrics(metric_type);
CREATE INDEX idx_metrics_timestamp ON metrics(timestamp);
CREATE INDEX idx_metrics_task_id ON metrics(task_id);
```

### Daily Metrics Table
```sql
CREATE TABLE daily_metrics (
    id INTEGER PRIMARY KEY,
    date VARCHAR(10) UNIQUE,
    data JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Monthly Metrics Table
```sql
CREATE TABLE monthly_metrics (
    id INTEGER PRIMARY KEY,
    year_month VARCHAR(7) UNIQUE,
    data JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 🔍 Querying Metrics

### Get Daily Metrics

```bash
curl http://localhost:8005/metrics/daily/2024-05-30 | jq
```

Response:
```json
{
  "date": "2024-05-30",
  "total_requests": 150,
  "successful_requests": 148,
  "failed_requests": 2,
  "avg_response_time_ms": 542.3,
  "total_agent_tasks": 50,
  "successful_tasks": 49,
  "failed_tasks": 1,
  "total_llm_calls": 100,
  "total_tokens": 5000,
  "total_llm_cost": 0.15,
  "total_social_messages": 25,
  "total_errors": 3,
  "system_health": "healthy"
}
```

### Get Monthly Metrics

```bash
curl http://localhost:8005/metrics/monthly/2024-05 | jq
```

### Get Efficiency Score

```bash
curl http://localhost:8005/metrics/efficiency-score?days=7 | jq
```

Response:
```json
{
  "score": 82.5,
  "reliability_score": 24.5,
  "latency_score": 23.0,
  "cost_efficiency_score": 18.0,
  "resource_utilization_score": 20.0,
  "recommendations": [
    "Improve task reliability - focus on error handling",
    "Review LLM usage patterns - consider cheaper models"
  ]
}
```

---

## 🚨 Alert Configuration

### Create Custom Alerts

```python
from shared.metrics_client import get_collector
from datetime import datetime, timedelta

async def check_alerts():
    # Get daily metrics
    today = datetime.utcnow().strftime("%Y-%m-%d")
    daily = await fetch_metrics(f"/daily/{today}")
    
    # Alert on high error rate
    if daily['total_errors'] > 10:
        send_alert("ERROR_RATE_HIGH", f"{daily['total_errors']} errors today")
    
    # Alert on slow response time
    if daily['avg_response_time_ms'] > 3000:
        send_alert("LATENCY_HIGH", f"{daily['avg_response_time_ms']}ms avg")
    
    # Alert on high cost
    if daily['total_llm_cost'] > 10:
        send_alert("COST_HIGH", f"${daily['total_llm_cost']:.2f} cost today")
```

---

## 📈 Performance Optimization Workflow

### 1. Identify Bottlenecks
- Check Performance tab
- Look at response time distribution
- Review error types

### 2. Set Goals
- Target success rate: 98%+
- Target response time: < 2s
- Target cost: < $0.01 per request

### 3. Implement Changes
- Optimize code
- Switch to cheaper models
- Add caching
- Improve error handling

### 4. Measure Impact
- Monitor daily/weekly metrics
- Compare with baseline
- Track efficiency score
- Check cost trends

### 5. Iterate
- Use recommendations from dashboard
- Test improvements
- Roll back if needed
- Document learnings

---

## 🔐 Security

### API Authentication
Currently, metrics API is internal only (localhost).

For production, add authentication:

```python
from fastapi import Depends, HTTPException, Header

async def verify_monitoring_key(x_api_key: str = Header()):
    if x_api_key != settings.monitoring_api_key:
        raise HTTPException(status_code=403)
    return x_api_key

@app.post("/metrics/collect")
async def collect(metric: MetricData, _=Depends(verify_monitoring_key)):
    ...
```

### Data Privacy
- Metrics don't include sensitive data
- Error messages sanitized
- PII stripped from logs
- Database encrypted at rest

---

## 🐛 Troubleshooting

### Metrics not appearing

```bash
# Check monitoring service is running
docker-compose ps monitoring

# Check logs
docker-compose logs monitoring

# Test metrics collection
curl -X POST http://localhost:8005/metrics/collect \
  -H "Content-Type: application/json" \
  -d '{"metric_type": "request", "status_code": 200}'
```

### Dashboard slow

```bash
# Check database performance
docker-compose exec postgres psql -c "ANALYZE;"

# Check metrics volume
docker-compose exec postgres \
  psql -c "SELECT COUNT(*) FROM metrics;"

# Archive old data
DELETE FROM metrics WHERE timestamp < NOW() - INTERVAL '30 days';
```

### High memory usage

```bash
# Check metrics table size
docker-compose exec postgres \
  psql -c "SELECT pg_size_pretty(pg_total_relation_size('metrics'));"

# Implement metric sampling
# In shared/metrics_client.py, add random sampling
```

---

## 📚 Related Documentation

- [README.md](../README.md) - Main guide
- [DASHBOARD.md](../DASHBOARD.md) - Dashboard user guide
- [MONITORING_INTEGRATION.md](../MONITORING_INTEGRATION.md) - Integration guide
- [ARCHITECTURE.md](../ARCHITECTURE.md) - System design

---

## 🎓 Learning Path

1. **Start** - Open dashboard at http://localhost:8006
2. **Explore** - Check each tab (Overview, Daily, Monthly, Performance, Costs)
3. **Understand** - Read DASHBOARD.md and MONITORING_INTEGRATION.md
4. **Integrate** - Add metrics to your services
5. **Optimize** - Use insights to improve efficiency
6. **Monitor** - Track improvements over time

---

**Version**: 1.0.0  
**Status**: Production Ready ✅  
**Last Updated**: May 30, 2026
