"""
Quick Start Guide - Get Running in 5 Minutes

This guide helps you get the Personal AI Agent Platform running locally.
"""

# ============================================
# STEP 1: Prerequisites Check
# ============================================

## Required:
- Python 3.12+: `python --version`
- Docker & Docker Compose: `docker --version && docker-compose --version`
- API Keys: OpenAI, Anthropic (optional for social/browser)

## Quick Install (Windows/Mac/Linux):
```bash
# Clone
git clone https://github.com/yourusername/personal-agent.git
cd personal-agent

# Copy config
cp .env.example .env

# IMPORTANT: Edit .env and add API keys
# Open .env in your editor and fill in:
#   OPENAI_API_KEY=sk-...
#   ANTHROPIC_API_KEY=sk-ant-...
```

# ============================================
# STEP 2: One-Command Setup
# ============================================

## Option A: Using Makefile (Linux/Mac)
```bash
make setup
make run
```

## Option B: Using Scripts (Windows)
```bash
setup.bat
docker-compose up -d
```

## Option C: Manual Setup
```bash
# 1. Create venv
python -m venv venv
source venv/bin/activate  # or: venv\Scripts\activate

# 2. Install deps
pip install -r requirements.txt

# 3. Start services
docker-compose up -d
```

# ============================================
# STEP 3: Verify Installation
# ============================================

```bash
# Check services are running
docker-compose ps

# Check health
curl http://localhost:8000/health

# View logs (troubleshoot if needed)
docker-compose logs gateway
```

# ============================================
# STEP 4: Test the API
# ============================================

## Option A: Using API Docs (GUI)
Open: http://localhost:8000/docs
1. Click "POST /execute"
2. Click "Try it out"
3. Paste example below
4. Click "Execute"

## Option B: Using cURL
```bash
curl -X POST http://localhost:8000/execute \
  -H "X-API-Key: change-this-in-production" \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Say hello and tell me what you can do",
    "session_id": "test_user_1"
  }'
```

## Option C: Using Python
```python
import requests

response = requests.post(
    "http://localhost:8000/execute",
    headers={"X-API-Key": "change-this-in-production"},
    json={
        "user_input": "Find iPhone 15 prices on Shopee",
        "session_id": "user_123"
    }
)

print(response.json())
```

# ============================================
# STEP 5: Try Real Examples
# ============================================

### Example 1: Simple Research
```json
{
  "user_input": "What's the current weather in Hanoi?"
}
```

### Example 2: Browser Automation
```json
{
  "user_input": "Search for Python tutorials and get top 3 results with links"
}
```

### Example 3: Desktop Control (if configured)
```json
{
  "user_input": "Take a screenshot of my desktop"
}
```

# ============================================
# STEP 6: Setup Social Media (Optional)
# ============================================

## For Facebook Fanpage:
1. Go to Facebook Developers (developers.facebook.com)
2. Create App → Messenger → Webhooks
3. In webhook config:
   - URL: http://your-domain.com/social/facebook/webhook
   - Verify Token: (use your FB_VERIFY_TOKEN from .env)
4. Subscribe to: messages, messaging_postbacks
5. Get PAGE_ACCESS_TOKEN → add to .env

## For Zalo OA:
1. Go to Zalo Developers (developers.zalo.me)
2. Create OA → Setup Webhook
3. Configure webhook URL: http://your-domain.com/social/zalo/webhook
4. Get access token → add to .env

# ============================================
# TROUBLESHOOTING
# ============================================

## Services won't start
```bash
# Check Docker status
docker ps

# Restart everything
docker-compose restart

# Check logs for errors
docker-compose logs
```

## Connection refused errors
```bash
# Make sure databases are running
docker-compose logs postgres redis qdrant

# Wait a few seconds and retry
sleep 5
curl http://localhost:8000/health
```

## API returns error
```bash
# Check API key in .env
cat .env | grep API_KEY

# Check service logs
docker-compose logs gateway

# Verify request format
curl -v http://localhost:8000/execute
```

## Out of memory
```bash
# Check Docker resource limits
docker stats

# Reduce container size
docker-compose down
docker system prune -a
docker-compose up -d
```

# ============================================
# NEXT STEPS
# ============================================

1. ✅ Services running locally
2. 📖 Read full README.md
3. 🔧 Customize prompts in PROMPTS.md
4. 🌐 Setup social integrations (optional)
5. 📦 Deploy to cloud (AWS/Azure/GCP)
6. 📊 Monitor via logs and dashboards

# ============================================
# USEFUL COMMANDS
# ============================================

# View all services
docker-compose ps

# View service logs
docker-compose logs -f gateway

# Restart a service
docker-compose restart gateway

# Open Python shell in container
docker-compose exec gateway python

# Database shell
docker-compose exec postgres psql -U postgres -d agent_db

# Stop all services
docker-compose down

# Clean up everything
docker-compose down -v

# Help
make help

# Reach out for help
# GitHub Issues: https://github.com/yourusername/personal-agent/issues
# Documentation: README.md and docs/
"""

print(__doc__)
