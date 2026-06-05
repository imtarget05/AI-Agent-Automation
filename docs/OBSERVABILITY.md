# Observability

PR 1 adds OpenTelemetry tracing and structured JSON logging.

Tracing is disabled by default:

```env
OTEL_ENABLED=false
```

When enabled, the following production paths create spans:

- `gateway.http_request`
- `orchestrator.workflow`
- `orchestrator.supervisor`
- `langgraph.node.execute`
- `agent.execute`
- `agent.remote_call`
- `llm.call`
- `rag.retrieval`
- `rag.vector_search`
- `rag.query_expansion`
- `rag.rerank`
- `rca.reasoning_step`
- `guardrail.input_check`
- `guardrail.tool_check`
- `approval.request`
- `email.compose`
- `aiops.analysis`
- `devops.analysis`

Structured logs use `shared/observability/logging.py` and include:

- `timestamp`
- `level`
- `service`
- `name`
- `message`
- `trace_id`
- `span_id`
- `request_id`
- `workflow_id`
- `session_id`
- `tenant_id`
- `user_id`
- `agent_name`

## Local Jaeger

Start the optional observability stack:

```bash
docker compose --profile observability up -d otel_collector jaeger
```

Open Jaeger:

```text
http://localhost:16686
```

Enable tracing:

```env
OTEL_ENABLED=true
OTEL_SERVICE_NAME=ai-agent-automation
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_TRACES_EXPORTER=otlp
OTEL_LOG_LEVEL=INFO
```

Inside Docker, services use `http://otel_collector:4317`.

## Usage

```python
from shared.observability.tracing import start_span, record_error

with start_span("agent.execute", {"workflow_id": workflow_id, "agent_name": "rca"}):
    ...
```

```python
from shared.observability.logging import get_logger, set_log_context

logger = get_logger(__name__)
set_log_context(request_id="req-1", workflow_id="wf-1")
logger.info("workflow started")
```

## Dependencies

`requirements.txt` includes:

```text
opentelemetry-api
opentelemetry-sdk
opentelemetry-exporter-jaeger
opentelemetry-exporter-otlp-proto-grpc
opentelemetry-exporter-otlp-proto-http
opentelemetry-instrumentation-fastapi
opentelemetry-instrumentation-httpx
python-json-logger
```

## Security

Do not log raw prompts, API keys, passwords, access tokens, refresh tokens, or unmasked PII. The local OTEL Collector config deletes common sensitive attribute keys before export.
