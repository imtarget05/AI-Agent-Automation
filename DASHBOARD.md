# 📊 System Monitoring Dashboard - User Guide

## Overview

The **AI Agent Platform Dashboard** provides comprehensive real-time monitoring and analytics for your system. It tracks performance, efficiency, costs, and system health across all agents and services.

**Dashboard URL**: `http://localhost:8006`  
**Monitoring API**: `http://localhost:8005`  

---

## 🎯 Key Features

### 1. **Real-Time Monitoring**
- Live system health status
- Service uptime tracking
- Active request monitoring
- Error alerts

### 2. **Daily Analytics**
- Request trends
- Task completion rates
- Response time distribution
- Error breakdown

### 3. **Monthly Reports**
- Cost analysis by model
- Agent efficiency metrics
- Long-term trends
- Performance trends

### 4. **Performance Scoring**
- Overall efficiency score (0-100)
- Reliability score (based on success rate)
- Latency score (response time)
- Cost efficiency score
- Resource utilization score

### 5. **Cost Analysis**
- Total costs by LLM model
- Cost per request
- Daily/monthly cost trends
- Cost optimization suggestions

---

## 📈 Dashboard Tabs

### **Overview Tab** (Default)
Comprehensive system status and metrics at a glance.

**Cards displayed:**
- **Total Requests** - API calls in last 7 days
- **Success Rate** - Percentage of successful tasks
- **Avg Response Time** - Average latency in milliseconds
- **Total Cost** - LLM API costs in last 7 days
- **Efficiency Score** - Overall system efficiency (0-100)
- **System Health** - Current system status

**Charts:**
- Request trends (last 7 days)
- Agent performance comparison
- Cost breakdown by model

**Service Status Table:**
- Real-time status of all services
- Gateway, Social Bot, Browser, Computer Use, Monitoring
- Last health check timestamp

---

### **Daily Analytics Tab**
Detailed metrics for a specific day.

**Time Range Options:**
- Today
- Yesterday
- Last 7 Days (averaged)

**Metrics Tracked:**
- Daily API requests
- Task executions
- Success/failure counts
- Error count
- LLM costs

**Performance Metrics:**
- Success rate %
- Average response time
- Completed vs failed tasks

---

### **Monthly Report Tab**
Aggregated monthly statistics and trends.

**High-Level Metrics:**
- Total monthly requests
- Total agent tasks
- Total LLM calls
- Total messages processed

**Financial Analysis:**
- Monthly total cost
- Cost per request
- Cost by LLM model
- Projected costs

**Reliability:**
- Average success rate
- Error rate
- Error type breakdown
- Uptime percentage

---

### **Performance Tab**
Detailed performance analysis and optimization recommendations.

**Efficiency Score Components:**
- **Reliability Score** (0-25): Based on task success rate
- **Latency Score** (0-25): Based on response time performance
- **Cost Efficiency Score** (0-25): Based on cost per request
- **Resource Utilization** (0-25): CPU/Memory usage

**Charts:**
- Response time distribution
- Success rate by agent
- Performance trends

**Recommendations:**
- Automated suggestions for improvement
- Priority levels (high, medium, low)
- Specific actions to take

---

### **Cost Analysis Tab**
Detailed financial metrics and optimization.

**Cost Metrics:**
- 7-day cost
- 30-day cost
- Projected monthly cost
- Cost per 1,000 requests

**Cost Breakdown:**
- Cost by LLM model
- Total calls per model
- Percentage of total cost

**Optimization Suggestions:**
- Identify expensive models
- Recommend cheaper alternatives
- Estimate savings

---

## 🔧 Configuration

### Environment Variables

The dashboard requires minimal configuration:

```bash
# .env file
MONITORING_URL=http://monitoring:8005    # Internal Docker URL
LOG_LEVEL=INFO
ENV=development
```

### Ports

- **Dashboard Frontend**: Port 8006
- **Monitoring API**: Port 8005

Ensure these ports are not blocked by firewall.

---

## 📊 Metrics Collected

### Request Metrics
- Endpoint called
- HTTP method
- Status code
- Response time (milliseconds)

### Agent Metrics
- Agent type (manager, computer_use, browser, social)
- Task ID
- Execution status (started, success, failed, timeout)
- Duration (milliseconds)

### LLM Metrics
- Model name
- Input tokens
- Output tokens
- Cost (USD)

### Social Metrics
- Platform (facebook, zalo)
- Message type (incoming, outgoing)
- Count

### Error Metrics
- Error type
- Error message
- Timestamp
- Context metadata

---

## 📈 Understanding Metrics

### Efficiency Score

The **Efficiency Score** (0-100) combines multiple factors:

```
Total Score = Reliability (0-25) + Latency (0-25) + Cost (0-25) + Resources (0-25)
```

**Interpretation:**
- **75-100**: Excellent - All systems optimal
- **50-74**: Good - Minor optimizations needed
- **25-49**: Warning - Significant improvements needed
- **0-24**: Critical - Immediate action required

### Success Rate

Percentage of agent tasks completed successfully.

```
Success Rate = (Successful Tasks / Total Tasks) × 100
```

**Target**: ≥ 98%

### Average Response Time

Mean time taken to complete requests.

**Target**: < 2,000 ms (2 seconds)

### Cost Per Request

Average cost per API request.

```
Cost Per Request = Total Cost / Total Requests
```

**Target**: < $0.01 per request

---

## 🎯 Performance Optimization Tips

### 1. Reduce Costs
- Review which models are most expensive
- Switch from GPT-4o to gpt-4o-mini for simple tasks
- Batch related requests

### 2. Improve Reliability
- Check error trends in Performance tab
- Review failed task logs
- Implement retry logic for failures

### 3. Optimize Latency
- Monitor response time distribution
- Identify slow endpoints
- Consider caching for repeated queries

### 4. Monitor Resources
- Track CPU and memory usage
- Scale services if needed
- Optimize database queries

---

## 🔄 Data Refresh

The dashboard automatically refreshes every **60 seconds**.

**Manual Refresh:**
- Click browser refresh button
- Or reload the page (F5)

**Real-Time Updates:**
- Health status updates immediately
- Metrics are aggregated and cached for 1 hour

---

## 📝 API Endpoints

The monitoring service exposes REST APIs for programmatic access:

### Collect Metrics

```bash
POST /metrics/collect
Content-Type: application/json

{
  "metric_type": "request",
  "endpoint": "/execute",
  "method": "POST",
  "status_code": 200,
  "response_time_ms": 123.45
}
```

### Get Daily Metrics

```bash
GET /metrics/daily/2024-05-30

Response:
{
  "date": "2024-05-30",
  "total_requests": 150,
  "successful_requests": 148,
  "failed_requests": 2,
  "avg_response_time_ms": 542.3,
  ...
}
```

### Get Monthly Metrics

```bash
GET /metrics/monthly/2024-05

Response:
{
  "year_month": "2024-05",
  "total_requests": 4500,
  "total_cost": 45.67,
  "cost_per_request": 0.0101,
  ...
}
```

### Get Efficiency Score

```bash
GET /metrics/efficiency-score?days=7

Response:
{
  "score": 82.5,
  "reliability_score": 24.5,
  "latency_score": 23.0,
  "cost_efficiency_score": 18.0,
  "resource_utilization_score": 20.0,
  "recommendations": [...]
}
```

### Get System Health

```bash
GET /metrics/current-health

Response:
{
  "status": "healthy",
  "gateway_online": true,
  "social_online": true,
  "browser_online": true,
  "computer_use_online": true,
  "recent_errors": [...]
}
```

---

## 🚨 Alerts & Warnings

The dashboard alerts you when:

### ⚠️ Yellow (Warning)
- Success rate drops below 95%
- Response time exceeds 3 seconds
- Cost per request exceeds $0.01
- Error rate increases

### 🔴 Red (Critical)
- Service goes offline
- Success rate drops below 80%
- Response time exceeds 5 seconds
- More than 5 errors in the last hour

---

## 🔌 Integrating Services

To send metrics from your service to the monitoring system:

### Python Example

```python
from shared.metrics_client import get_collector

collector = get_collector("http://localhost:8005")

# Record API request
await collector.record_request(
    endpoint="/execute",
    method="POST",
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

# Record LLM call
await collector.record_llm_call(
    model_name="gpt-4o",
    input_tokens=100,
    output_tokens=50,
    cost_usd=0.003
)

# Record error
await collector.record_error(
    error_type="TimeoutError",
    error_message="Request timed out after 30 seconds"
)
```

### FastAPI Middleware Example

```python
from fastapi import FastAPI
from shared.metrics_client import get_collector, TimedOperation

app = FastAPI()
collector = get_collector()

@app.middleware("http")
async def metrics_middleware(request, call_next):
    async with TimedOperation(
        collector,
        "request",
        endpoint=request.url.path,
        method=request.method
    ):
        response = await call_next(request)
        await collector.record_request(
            endpoint=request.url.path,
            method=request.method,
            status_code=response.status_code
        )
        return response
```

---

## 🐛 Troubleshooting

### Dashboard not loading
1. Check monitoring service is running: `docker-compose ps monitoring`
2. Verify port 8005 is accessible
3. Check browser console for JavaScript errors

### No metrics showing
1. Verify services are sending metrics
2. Check monitoring service logs: `docker-compose logs monitoring`
3. Confirm database is connected

### Slow dashboard performance
1. Clear browser cache
2. Check database query performance
3. Review monitoring service logs for errors

---

## 📚 Related Documentation

- [README.md](../README.md) - Main project guide
- [ARCHITECTURE.md](../ARCHITECTURE.md) - System design
- [PROJECT_SUMMARY.md](../PROJECT_SUMMARY.md) - Overview

---

**Dashboard Version**: 1.0.0  
**Last Updated**: May 30, 2026  
**Status**: Production Ready ✅
