# Multi-stage Dockerfile for AI Agent Platform

FROM python:3.12-slim as base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy shared dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browser agent needs Playwright
RUN playwright install chromium --with-deps

# ──── Service-specific images ----

# Gateway
FROM base as gateway
COPY apps/gateway /app/apps/gateway
COPY shared /app/shared
CMD ["uvicorn", "apps.gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Social
FROM base as social
COPY apps/social /app/apps/social
COPY shared /app/shared
CMD ["uvicorn", "apps.social.main:app", "--host", "0.0.0.0", "--port", "8002"]

# Browser
FROM base as browser
COPY apps/browser /app/apps/browser
COPY shared /app/shared
CMD ["uvicorn", "apps.browser.main:app", "--host", "0.0.0.0", "--port", "8003"]

# Computer Use
FROM base as computer_use
RUN apt-get update && apt-get install -y --no-install-recommends \
    xdotool \
    xclip \
    python3-tk \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pyautogui pillow
COPY apps/computer-use /app/apps/computer-use
COPY shared /app/shared
CMD ["uvicorn", "apps.computer_use.main:app", "--host", "0.0.0.0", "--port", "8004"]

# Monitoring
FROM base as monitoring
COPY apps/monitoring /app/apps/monitoring
COPY shared /app/shared
CMD ["uvicorn", "apps.monitoring.main:app", "--host", "0.0.0.0", "--port", "8005"]

# Dashboard
FROM base as dashboard
COPY apps/dashboard /app/apps/dashboard
COPY shared /app/shared
CMD ["uvicorn", "apps.dashboard.main:app", "--host", "0.0.0.0", "--port", "8006"]

# RAG Service
FROM base as rag_service
COPY services/rag_service /app/services/rag_service
COPY services/__init__.py /app/services/__init__.py
COPY shared /app/shared
CMD ["uvicorn", "services.rag_service.main:app", "--host", "0.0.0.0", "--port", "8007"]

# ──---- Build instruction ----
# docker build --target gateway -t agent_gateway:latest .
# docker build --target social -t agent_social:latest .
# docker build --target browser -t agent_browser:latest .
# docker build --target computer_use -t agent_computer_use:latest .
# docker build --target monitoring -t agent_monitoring:latest .
# docker build --target dashboard -t agent_dashboard:latest .
# docker build --target rag_service -t agent_rag_service:latest .
