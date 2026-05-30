.PHONY: help setup install run stop logs clean test

help:
	@echo "🤖 Personal AI Agent Platform"
	@echo ""
	@echo "Available commands:"
	@echo "  make setup        - Initial setup (create .env, venv, Docker services)"
	@echo "  make install      - Install dependencies"
	@echo "  make run          - Start all services"
	@echo "  make stop         - Stop all services"
	@echo "  make logs         - View service logs"
	@echo "  make test         - Run tests"
	@echo "  make clean        - Clean up containers and cache"
	@echo ""

setup:
	@echo "🚀 Setting up project..."
	@test -f .env || cp .env.example .env
	@echo "✅ .env created. Please edit with your API keys."
	python3.12 -m venv venv
	./venv/bin/pip install -r requirements.txt
	docker-compose up -d postgres redis qdrant
	@echo "✅ Setup complete! Start services with: make run"

install:
	pip install -r requirements.txt
	playwright install chromium

run:
	docker-compose up -d

stop:
	docker-compose down

logs:
	docker-compose logs -f

logs-gateway:
	docker-compose logs -f gateway

logs-social:
	docker-compose logs -f social

logs-browser:
	docker-compose logs -f browser

logs-computer:
	docker-compose logs -f computer_use

test:
	pytest tests/ -v

clean:
	docker-compose down
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov

ps:
	docker-compose ps

health:
	curl -s http://localhost:8000/health | jq

health-all:
	@echo "Gateway:"
	@curl -s http://localhost:8000/health | jq .
	@echo "\nSocial:"
	@curl -s http://localhost:8002/health | jq .
	@echo "\nBrowser:"
	@curl -s http://localhost:8003/health | jq .
	@echo "\nComputer Use:"
	@curl -s http://localhost:8004/health | jq .

shell-gateway:
	docker-compose exec gateway bash

shell-postgres:
	docker-compose exec postgres psql -U postgres -d agent_db

shell-redis:
	docker-compose exec redis redis-cli

build:
	docker-compose build

rebuild:
	docker-compose build --no-cache

docs:
	@echo "API Docs: http://localhost:8000/docs"
	@echo "ReDoc: http://localhost:8000/redoc"
