.PHONY: help dev prod stop logs test smoke lint format security clean \
        ingest-docs demo health health-all build rebuild shell-gateway \
        shell-redis precommit-install precommit-run

# ── Colours ─────────────────────────────────────────────────────────────────
GREEN  := \033[0;32m
YELLOW := \033[0;33m
CYAN   := \033[0;36m
RESET  := \033[0m

help:
	@echo ""
	@echo "$(CYAN)🤖 AI-Agent-Automation Platform$(RESET)"
	@echo ""
	@echo "$(YELLOW)Development$(RESET)"
	@echo "  make dev            — Start all services in dev mode (mock infra, hot-reload)"
	@echo "  make stop           — Stop all running containers"
	@echo "  make logs           — Tail all service logs"
	@echo "  make logs-gateway   — Tail gateway logs only"
	@echo ""
	@echo "$(YELLOW)Testing$(RESET)"
	@echo "  make test           — Run full test suite with coverage"
	@echo "  make test-unit      — Run unit tests only (fast, no deps)"
	@echo "  make smoke          — Run smoke tests against local gateway"
	@echo "  make smoke-staging  — Run smoke tests against STAGING_GATEWAY_URL"
	@echo ""
	@echo "$(YELLOW)Code Quality$(RESET)"
	@echo "  make lint           — Ruff lint check"
	@echo "  make format         — Auto-format with ruff"
	@echo "  make security       — Bandit SAST + safety dependency scan"
	@echo "  make precommit-run  — Run pre-commit hooks on all files"
	@echo ""
	@echo "$(YELLOW)Data & Demo$(RESET)"
	@echo "  make ingest-docs    — Ingest docs/ folder into RAG vector store"
	@echo "  make demo           — Run end-to-end incident demo with mock data"
	@echo ""
	@echo "$(YELLOW)Infrastructure$(RESET)"
	@echo "  make build          — Build all Docker images"
	@echo "  make health         — Check gateway health"
	@echo "  make health-all     — Check health of all services"
	@echo "  make setup          — First-time project setup"
	@echo ""

# ── Dev & Prod ───────────────────────────────────────────────────────────────

setup:
	@echo "$(CYAN)🚀 Setting up project...$(RESET)"
	@test -f .env || cp .env.example .env
	@echo "$(GREEN)✅ .env created — please edit with your API keys$(RESET)"
	python3 -m venv venv 2>/dev/null || python -m venv venv
	./venv/bin/pip install -r requirements.txt 2>/dev/null || venv/Scripts/pip install -r requirements.txt
	docker compose up -d redis qdrant
	@echo "$(GREEN)✅ Setup complete! Run: make dev$(RESET)"

dev:
	@echo "$(CYAN)🔧 Starting dev environment (mock infra, hot-reload)...$(RESET)"
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d \
		--remove-orphans \
		redis qdrant \
		gateway aiops_agent rca_agent devops_agent report_agent \
		email_agent guardrail_service approval_service \
		rag_service tool_service eval_service monitoring dashboard
	@echo ""
	@echo "$(GREEN)✅ Dev stack running:$(RESET)"
	@echo "   Gateway:   http://localhost:8000/docs"
	@echo "   Dashboard: http://localhost:8006"
	@echo "   Monitoring:http://localhost:8005"
	@echo "   API Key:   dev-secret-key-change-in-prod"

prod:
	@echo "$(CYAN)🏭 Starting production stack...$(RESET)"
	docker compose up -d --remove-orphans
	@echo "$(GREEN)✅ Production stack started$(RESET)"

stop:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml down

logs:
	docker compose logs -f --tail=100

logs-gateway:
	docker compose logs -f gateway

logs-agents:
	docker compose logs -f aiops_agent rca_agent devops_agent report_agent

# ── Testing ──────────────────────────────────────────────────────────────────

test:
	@echo "$(CYAN)🧪 Running full test suite...$(RESET)"
	pytest tests/ -v \
		--cov=apps --cov=services --cov=shared --cov=tools \
		--cov-report=term-missing \
		--cov-report=html:htmlcov \
		--tb=short

test-unit:
	@echo "$(CYAN)🧪 Running unit tests only...$(RESET)"
	pytest tests/ -v -m "unit" --tb=short

smoke:
	@echo "$(CYAN)💨 Smoke testing local gateway...$(RESET)"
	STAGING_GATEWAY_URL=http://localhost:8000 \
	STAGING_API_KEY=dev-secret-key-change-in-prod \
	pytest tests/smoke/ -v -m "smoke" --timeout=30 --tb=short

smoke-staging:
	@echo "$(CYAN)💨 Smoke testing staging gateway...$(RESET)"
	pytest tests/smoke/ -v -m "smoke" --timeout=60 --tb=short

# ── Code Quality ─────────────────────────────────────────────────────────────

lint:
	@echo "$(CYAN)🔍 Linting with ruff...$(RESET)"
	ruff check . --output-format=concise

format:
	@echo "$(CYAN)✨ Formatting with ruff...$(RESET)"
	ruff format .
	ruff check . --fix

security:
	@echo "$(CYAN)🔒 Running security scans...$(RESET)"
	bandit -r apps/ services/ shared/ tools/ -ll --format text
	safety check -r requirements.txt

precommit-install:
	pip install pre-commit
	pre-commit install
	@echo "$(GREEN)✅ Pre-commit hooks installed$(RESET)"

precommit-run:
	pre-commit run --all-files

# ── Data & Demo ──────────────────────────────────────────────────────────────

ingest-docs:
	@echo "$(CYAN)📚 Ingesting docs/ into RAG vector store...$(RESET)"
	@curl -s http://localhost:8000/health > /dev/null || (echo "$(YELLOW)⚠️  Gateway not running. Run: make dev$(RESET)" && exit 1)
	curl -s -X POST http://localhost:8007/ingest \
		-H "Content-Type: application/json" \
		-d '{"docs_path": "docs", "collection": "rag_documents"}' | python3 -m json.tool
	@echo "$(GREEN)✅ Docs ingested into Qdrant$(RESET)"

demo:
	@echo "$(CYAN)🎬 Running end-to-end incident demo...$(RESET)"
	python3 demo.py

# ── Infrastructure ───────────────────────────────────────────────────────────

build:
	docker compose build

rebuild:
	docker compose build --no-cache

health:
	@curl -sf http://localhost:8000/health | python3 -m json.tool || echo "Gateway not reachable"

health-all:
	@echo "$(CYAN)🏥 Service health matrix:$(RESET)"
	@for svc in "Gateway:8000" "Monitoring:8005" "Dashboard:8006" "RAG:8007" \
	            "Tools:8008" "Email:8009" "Guardrail:8010" "Approval:8011" \
	            "Report:8012" "AIOps:8013" "RCA:8014" "DevOps:8015" "Eval:8016"; do \
		name=$$(echo $$svc | cut -d: -f1); \
		port=$$(echo $$svc | cut -d: -f2); \
		status=$$(curl -sf http://localhost:$$port/health 2>/dev/null && echo "✅" || echo "❌ DOWN"); \
		echo "  $$name ($$port): $$status"; \
	done

shell-gateway:
	docker compose exec gateway bash

shell-redis:
	docker compose exec redis redis-cli

shell-postgres:
	docker compose exec postgres psql -U postgres -d agent_db

ps:
	docker compose ps

clean:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov .ruff_cache
	@echo "$(GREEN)✅ Clean complete$(RESET)"

docs:
	@echo "$(CYAN)📖 API Documentation:$(RESET)"
	@echo "   Swagger UI: http://localhost:8000/docs"
	@echo "   ReDoc:      http://localhost:8000/redoc"
	@echo "   OpenAPI:    http://localhost:8000/openapi.json"
