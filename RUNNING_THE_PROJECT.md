# Running the Project - Step-by-Step Guide

## 🚀 3-Step Quick Start

### Step 1: Prepare (5 min)
```bash
# Clone/enter project directory
cd personal-agent

# Copy configuration template
cp .env.example .env

# Edit .env with your API keys
# Minimum required: OPENAI_API_KEY + ANTHROPIC_API_KEY
nano .env  # or use your editor
```

### Step 2: Setup (2 min - Windows, 3 min - Linux/Mac)
```bash
# Windows (requires Python 3.12+ in PATH)
setup.bat

# Linux/Mac
./setup.sh

# This will:
# 1. Create .env if missing
# 2. Create Python virtual environment
# 3. Install all dependencies
# 4. Start PostgreSQL, Redis, Qdrant via Docker
```

### Step 3: Run (1 min)
```bash
# Start all services
docker-compose up -d

# Verify everything is running
docker-compose ps

# Check health
curl http://localhost:8000/health

# View logs (if any errors)
docker-compose logs gateway
```

---

## ✅ Verification Checklist

Run these commands to verify setup:

```bash
# 1. All containers running?
docker-compose ps
# Expected: 7 containers (gateway, social, browser, computer, postgres, redis, qdrant)

# 2. Gateway responsive?
curl http://localhost:8000/health
# Expected: {"status": "ok", ...}

# 3. Database accessible?
docker-compose exec postgres psql -U postgres -d agent_db -c "SELECT 1"
# Expected: (1 row)

# 4. Redis working?
docker-compose exec redis redis-cli ping
# Expected: PONG

# 5. API docs available?
open http://localhost:8000/docs
# Expected: Swagger UI loads

# 6. All services healthy?
curl -s http://localhost:8000/health && \
curl -s http://localhost:8002/health && \
curl -s http://localhost:8003/health && \
curl -s http://localhost:8004/health
# Expected: All return {"status": "ok"}
```

---

## 🧪 Test the API

### Option A: Interactive Testing (Recommended)
```bash
# Open browser
open http://localhost:8000/docs

# Use Swagger UI:
# 1. Click "POST /execute"
# 2. Click "Try it out"
# 3. Replace example with:
{
  "user_input": "Say hello and tell me what you can do",
  "session_id": "test_user_1"
}
# 4. Click "Execute"
# 5. Should see plan + result below
```

### Option B: Terminal Testing
```bash
# Simple test
curl -X POST http://localhost:8000/execute \
  -H "X-API-Key: change-this-in-production" \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Hello, what can you do?",
    "session_id": "test_user_1"
  }'

# Pretty print response
curl -X POST http://localhost:8000/execute \
  -H "X-API-Key: change-this-in-production" \
  -H "Content-Type: application/json" \
  -d '{"user_input": "Hello"}' | jq .
```

### Option C: Python Testing
```python
import requests

response = requests.post(
    "http://localhost:8000/execute",
    headers={"X-API-Key": "change-this-in-production"},
    json={
        "user_input": "Find the time",
        "session_id": "test_123"
    }
)

print(response.json())
```

---

## 📊 Monitor Services

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f gateway      # API
docker-compose logs -f social       # Social bots
docker-compose logs -f browser      # Browser agent
docker-compose logs -f computer_use # Computer agent

# Last 100 lines
docker-compose logs --tail=100 gateway

# Follow only errors
docker-compose logs -f gateway | grep ERROR
```

### Service Health
```bash
# Check all services
docker-compose ps

# Resource usage
docker stats

# Database status
docker-compose exec postgres pg_isready

# Redis info
docker-compose exec redis redis-cli info

# Qdrant status
curl http://localhost:6333/health
```

---

## 🔧 Configuration & Customization

### Change LLM Models
Edit `shared/llm.py`:
```python
TASK_MODEL_MAP = {
    "classification": "gpt-4o-mini",      # Change this
    "summarize": "gpt-4o-mini",
    "research": "gpt-4o",
    "computer_use": "claude-3-opus-20240229",  # or any other
}
```

### Customize Prompts
Edit `PROMPTS.md` or individual agent files:
- `apps/social/facebook.py` → `FACEBOOK_SYSTEM_PROMPT`
- `apps/social/zalo.py` → `ZALO_SYSTEM_PROMPT`
- `apps/gateway/orchestrator.py` → `MANAGER_PROMPT`

### Add Environment Variables
```bash
# Edit .env
nano .env

# Then restart services
docker-compose restart
```

---

## 🌐 Test Social Media Integration (Optional)

### Test Facebook Without Real Webhook
```bash
# Simulate Facebook webhook
curl -X POST http://localhost:8002/facebook/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "messaging": [{
        "sender": {"id": "user_123"},
        "recipient": {"id": "page_123"},
        "message": {"text": "Do you have iPhone?"}
      }]
    }]
  }'

# Check the reply would be generated
docker-compose logs social | grep "Message from user_123"
```

### Test Zalo Without Real Webhook
```bash
# Similar structure for Zalo
curl -X POST http://localhost:8002/zalo/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "sender": {"id": "zalo_user_123"},
    "message": {"text": "Product query"}
  }'
```

---

## 🔌 Setup Real Webhooks (Optional)

### Facebook Messenger Setup

1. **Go to Facebook Developers**
   ```
   https://developers.facebook.com
   → Your Apps → Select your app → Messenger
   ```

2. **Get Page Access Token**
   - Messenger Settings → Token Generation
   - Copy token to `.env` as `FB_PAGE_TOKEN`

3. **Setup Webhook**
   - Webhook URL: `https://your-domain.com/social/facebook/webhook`
   - Verify Token: Use `FB_VERIFY_TOKEN` from `.env`
   - Subscriptions: Select `messages`, `messaging_postbacks`

4. **Expose Local Dev (Optional)**
   ```bash
   # Use ngrok for local testing
   ngrok http 8002
   
   # Use ngrok URL in Facebook webhook setup
   # https://xxx.ngrok.io/social/facebook/webhook
   ```

### Zalo OA Setup

1. **Go to Zalo Developers**
   ```
   https://developers.zalo.me
   → My Applications → Create OA
   ```

2. **Setup Webhook**
   - Webhook URL: `https://your-domain.com/social/zalo/webhook`
   - Server Key: Add to `.env` as `ZALO_SERVER_KEY`

3. **Get OA Access Token**
   - Copy to `.env` as `ZALO_OA_TOKEN`

---

## 🛑 Stop & Cleanup

### Stop Services (Keep data)
```bash
docker-compose stop

# Later: restart
docker-compose start
```

### Stop Services (Remove containers, keep data)
```bash
docker-compose down
```

### Full Cleanup (Remove everything including data)
```bash
docker-compose down -v
```

### Remove images
```bash
docker-compose down --rmi all
```

---

## 🐛 Troubleshooting

### Problem: Port 8000 already in use
```bash
# Find process using port
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# Stop it or use different port
# Edit docker-compose.yml: "8001:8000"
```

### Problem: Docker daemon not running
```bash
# Start Docker Desktop or daemon
docker daemon  # or open Docker Desktop app

# Test
docker ps
```

### Problem: Out of memory
```bash
# Check usage
docker stats

# Reduce memory limit in docker-compose.yml
# Or stop other containers
```

### Problem: Database migrations failed
```bash
# Check database status
docker-compose logs postgres

# Try recreating database
docker-compose down -v
docker-compose up -d postgres
docker-compose logs postgres
```

### Problem: API returns 403 Forbidden
```bash
# Check API key matches
grep API_SECRET_KEY .env

# Use correct key in X-API-Key header
curl -X GET http://localhost:8000/health \
  -H "X-API-Key: $(grep API_SECRET_KEY .env | cut -d= -f2)"
```

---

## 📚 Next Steps

1. ✅ Verify all services running (5 min)
2. ✅ Test basic API call (2 min)
3. 📖 Read README.md for details (10 min)
4. 🔧 Customize prompts (PROMPTS.md) (15 min)
5. 🌐 Setup Facebook/Zalo webhooks (optional) (20 min)
6. 🚀 Deploy to cloud (see README deployment section) (1-2 hours)

---

## 💡 Pro Tips

### Use Makefile for common tasks
```bash
make help           # Show all commands
make logs           # View logs
make health         # Check health
make clean          # Cleanup
make ps             # List services
```

### Useful aliases (bash/zsh)
```bash
alias agent-logs="docker-compose logs -f gateway"
alias agent-status="docker-compose ps"
alias agent-health="curl -s http://localhost:8000/health | jq"
```

### Development mode (auto-reload)
Services are already configured with `--reload` flag in development:
```bash
# Changes to Python files auto-reload services
# Just edit and save - services restart automatically
```

### Debug mode
```bash
# View detailed logs
docker-compose logs -f --tail=200 gateway

# SSH into container
docker-compose exec gateway bash

# Run Python directly in container
docker-compose exec gateway python3 -c "import shared.llm; print('OK')"
```

---

## 🎯 Common Tasks

### Add new API endpoint
1. Edit `apps/gateway/main.py`
2. Add `@app.get()` or `@app.post()`
3. Service auto-reloads
4. Test via `/docs`

### Change response format
Edit models in `shared/models.py`, services auto-update

### Add custom system prompt
Edit `PROMPTS.md`, update agent files, restart services

### Monitor database
```bash
docker-compose exec postgres psql -U postgres -d agent_db
# Then: \dt (show tables), SELECT * FROM users;
```

### Reset API key
```bash
# Generate new one
echo "API_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env

# Update header in requests
curl -H "X-API-Key: $(grep API_SECRET_KEY .env | cut -d= -f2)" ...
```

---

**Happy building! 🚀**

For detailed information, see:
- [README.md](README.md) - Full documentation
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [PROMPTS.md](PROMPTS.md) - Prompt templates
- [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) - Overview
