# Multi-stage hardened Dockerfile for AI Agent Platform

FROM python:3.12-slim as base

WORKDIR /app

# Install system dependencies & clean apt cache to minimize image size
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user and group for runtime safety
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup --create-home --shell /bin/bash appuser && \
    chown -R appuser:appgroup /app

# Copy shared dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browser agent needs Playwright
RUN playwright install chromium --with-deps && \
    chown -R appuser:appgroup /home/appuser/.cache || true

# ──── Service-specific images ----

# Gateway
FROM base as gateway
COPY apps/gateway /app/apps/gateway
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "apps.gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Social
FROM base as social
COPY apps/social /app/apps/social
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8002/health || exit 1
CMD ["uvicorn", "apps.social.main:app", "--host", "0.0.0.0", "--port", "8002"]

# Browser
FROM base as browser
COPY apps/browser /app/apps/browser
COPY shared /app/shared
# Run as appuser since we adjusted playwright cache permissions
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8003/health || exit 1
CMD ["uvicorn", "apps.browser.main:app", "--host", "0.0.0.0", "--port", "8003"]

# Computer Use
FROM base as computer_use
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    xdotool \
    xclip \
    python3-tk \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pyautogui pillow
COPY apps/computer_use /app/apps/computer_use
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8004/health || exit 1
CMD ["uvicorn", "apps.computer_use.main:app", "--host", "0.0.0.0", "--port", "8004"]

# Monitoring
FROM base as monitoring
COPY apps/monitoring /app/apps/monitoring
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8005/health || exit 1
CMD ["uvicorn", "apps.monitoring.main:app", "--host", "0.0.0.0", "--port", "8005"]

# Dashboard
FROM base as dashboard
COPY apps/dashboard /app/apps/dashboard
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8006/health || exit 1
CMD ["uvicorn", "apps.dashboard.main:app", "--host", "0.0.0.0", "--port", "8006"]

# RAG Service
FROM base as rag_service
COPY services/rag_service /app/services/rag_service
COPY services/__init__.py /app/services/__init__.py
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8007/health || exit 1
CMD ["uvicorn", "services.rag_service.main:app", "--host", "0.0.0.0", "--port", "8007"]

# Tool Service
FROM base as tool_service
COPY tools /app/tools
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8008/health || exit 1
CMD ["uvicorn", "tools.main:app", "--host", "0.0.0.0", "--port", "8008"]

# Email Agent
FROM base as email_agent
COPY apps/email_agent /app/apps/email_agent
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8009/health || exit 1
CMD ["uvicorn", "apps.email_agent.main:app", "--host", "0.0.0.0", "--port", "8009"]

# Guardrail Service
FROM base as guardrail_service
COPY services/guardrail_service /app/services/guardrail_service
COPY services/__init__.py /app/services/__init__.py
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8010/health || exit 1
CMD ["uvicorn", "services.guardrail_service.main:app", "--host", "0.0.0.0", "--port", "8010"]

# Approval Service
FROM base as approval_service
COPY services/approval_service /app/services/approval_service
COPY services/__init__.py /app/services/__init__.py
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8011/health || exit 1
CMD ["uvicorn", "services.approval_service.main:app", "--host", "0.0.0.0", "--port", "8011"]

# Report Agent
FROM base as report_agent
COPY apps/report_agent /app/apps/report_agent
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8012/health || exit 1
CMD ["uvicorn", "apps.report_agent.main:app", "--host", "0.0.0.0", "--port", "8012"]

# AIOps Agent
FROM base as aiops_agent
COPY apps/aiops_agent /app/apps/aiops_agent
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8013/health || exit 1
CMD ["uvicorn", "apps.aiops_agent.main:app", "--host", "0.0.0.0", "--port", "8013"]

# RCA Agent
FROM base as rca_agent
COPY apps/rca_agent /app/apps/rca_agent
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8014/health || exit 1
CMD ["uvicorn", "apps.rca_agent.main:app", "--host", "0.0.0.0", "--port", "8014"]

# DevOps Agent
FROM base as devops_agent
COPY apps/devops_agent /app/apps/devops_agent
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8015/health || exit 1
CMD ["uvicorn", "apps.devops_agent.main:app", "--host", "0.0.0.0", "--port", "8015"]

# Evaluation Service
FROM base as eval_service
COPY services/eval_service /app/services/eval_service
COPY services/__init__.py /app/services/__init__.py
COPY shared /app/shared
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8016/health || exit 1
CMD ["uvicorn", "services.eval_service.main:app", "--host", "0.0.0.0", "--port", "8016"]
