# 🤖 Personal AI Agent Platform

> A production-grade multi-agent AI system that automatically controls your desktop, browses the web, and manages your social media.

**Status**: ✅ Architecture Complete | 🔨 Core Modules Built | 🚀 Ready for Deployment

---

## 📋 Overview

This project implements a **sophisticated multi-agent orchestration system** where:

1. **Manager Agent** (LangGraph) - Analyzes user requests and creates execution plans
2. **Browser Agent** - Automates web browsing and data extraction using `browser-use`
3. **Social Media Bot** - Auto-replies to Facebook Fanpage & Zalo OA messages
4. **Computer Use Agent** - Controls your desktop (click, type, take screenshots)

All agents are orchestrated through a central **FastAPI Gateway** with shared **LLM Router** and **Memory Layer**.

---

## 🏗️ Architecture

### System Design

```
┌─────────────────────────────────────────────────────────┐
│                     FastAPI Gateway                      │
│         (Entry point for all requests)                  │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────┼───────────┐
         │           │           │
    ┌────▼────┐  ┌──▼──┐  ┌─────▼────┐
    │LangGraph │  │Task │  │Session   │
    │Manager   │  │State│  │Memory    │
    └────┬────┘  └─────┘  └──────────┘
         │
    ┌────┴──────────────────────┬─────────────────┐
    │                           │                 │
┌───▼────────┐  ┌──────────┐  ┌▼────────┐  ┌─────▼──────┐
│  Computer  │  │ Browser  │  │ Social  │  │LLM Router  │
│  Use Agent │  │ Agent    │  │ Bot     │  │(LiteLLM)   │
└────────────┘  └──────────┘  └─────────┘  └────────────┘
     │               │            │              │
     └───────────────┴────────────┴──────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
    ┌───▼──┐  ┌─────▼───┐  ┌─────▼──┐
    │Redis │  │ Qdrant  │  │ PostgreSQL
    │Cache │  │ Vectors │  │ Storage
    └──────┘  └─────────┘  └────────┘
```

### Folder Structure

```
personal-agent/
├── apps/
│   ├── gateway/              # FastAPI + LangGraph Orchestrator
│   │   ├── main.py          # API endpoints
│   │   ├── orchestrator.py   # LangGraph workflow
│   │   └── __init__.py
│   ├── social/               # FB Fanpage + Zalo OA
│   │   ├── main.py          # Combined webhook handler
│   │   ├── facebook.py       # Facebook Messenger
│   │   ├── zalo.py           # Zalo OA
│   │   └── __init__.py
│   ├── browser/              # Web automation
│   │   ├── main.py          # Browser API
│   │   ├── agent.py         # Browser-use integration
│   │   └── __init__.py
│   └── computer-use/         # Desktop automation
│       ├── main.py          # Computer use API
│       ├── agent.py         # Anthropic Computer Use
│       └── __init__.py
├── shared/                   # Shared infrastructure
│   ├── config.py            # Settings (env vars)
│   ├── llm.py               # LLM router with cost optimization
│   ├── memory.py            # Vector + Session memory
│   ├── models.py            # Pydantic schemas
│   └── __init__.py
├── docker-compose.yml       # Services orchestration
├── Dockerfile               # Multi-stage build
├── requirements.txt         # Python dependencies
├── .env.example             # Configuration template
├── setup.sh / setup.bat     # Initialization scripts
└── README.md               # This file
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+**
- **Docker & Docker Compose**
- **API Keys** (OpenAI, Anthropic, Facebook, Zalo)

### 1. Clone & Setup

```bash
git clone https://github.com/yourusername/personal-agent.git
cd personal-agent

# Create .env file
cp .env.example .env
# ⚠️ Edit .env and add your API keys!

# For Windows
setup.bat

# For Linux/Mac
chmod +x setup.sh
./setup.sh
```

### 2. Configure API Keys

Edit `.env`:

```env
# LLM Keys (required)
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...

# Social (optional, needed only for that module)
FB_PAGE_TOKEN=your_token
FB_VERIFY_TOKEN=webhook_secret
ZALO_OA_TOKEN=your_oa_token
ZALO_SERVER_KEY=your_server_key

# Security
API_SECRET_KEY=change-this-in-production
```

### 3. Start Services

```bash
# Start all services (Gateway, DB, Cache, Vector Store)
docker-compose up -d

# Watch logs
docker-compose logs -f gateway

# Check health
curl http://localhost:8000/health
```

### 4. Test the API

```bash
# Get API docs
open http://localhost:8000/docs

# Test execution endpoint
curl -X POST http://localhost:8000/execute \
  -H "X-API-Key: change-this-in-production" \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Find iPhone 15 prices on Shopee and compare top 3",
    "session_id": "user_123"
  }'
```

---

## 🔌 Integration Guides

### Facebook Messenger Setup

1. Go to [Facebook Developers](https://developers.facebook.com)
2. Create an App → Messenger
3. Setup Webhook:
   - URL: `https://your-domain.com/social/facebook/webhook`
   - Verify Token: Use value from `.env` `FB_VERIFY_TOKEN`
   - Subscriptions: `messages`, `messaging_postbacks`

4. Get Page Access Token and add to `.env`:
   ```env
   FB_PAGE_TOKEN=EAA...
   ```

### Zalo OA Setup

1. Go to [Zalo Developers](https://developers.zalo.me)
2. Create OA → Webhook Settings
3. Setup Webhook:
   - URL: `https://your-domain.com/social/zalo/webhook`
   - Server Key: Add to `.env`

4. Get OA Token and add to `.env`:
   ```env
   ZALO_OA_TOKEN=your_oa_token
   ```

### Browser Agent Setup

The browser agent uses `browser-use` library which requires:

```bash
pip install browser-use
playwright install chromium
```

For advanced web scraping:

```python
# apps/browser/agent.py
# Customize selectors and extraction logic
```

### Computer Use Setup

**Option 1: Anthropic Computer Use (Recommended)**
- Requires Claude 3.5 Sonnet API access
- Set `ANTHROPIC_API_KEY` in `.env`

**Option 2: PyAutoGUI Fallback**
- Lightweight alternative
- Requires desktop environment (X11 on Linux)

---

## 📡 API Endpoints

### Gateway (Port 8000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/execute` | Execute task across agents |
| `POST` | `/execute-async` | Async task execution |
| `GET` | `/task-status/{task_id}` | Get async task status |
| `POST` | `/session` | Create new session |
| `GET` | `/session/{session_id}/history` | Get conversation history |
| `GET` | `/health` | Health check |

### Social Bot (Port 8002)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/facebook/webhook` | Facebook Messenger webhook |
| `POST` | `/zalo/webhook` | Zalo OA webhook |

### Browser Agent (Port 8003)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/execute` | Execute browser task |
| `POST` | `/search` | Search web |

### Computer Use (Port 8004)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/execute` | Execute computer task |
| `POST` | `/screenshot` | Take screenshot |
| `POST` | `/click` | Click at position |

---

## 💡 Usage Examples

### Example 1: Research Task

```bash
curl -X POST http://localhost:8000/execute \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Find the latest iPhone 15 Pro prices from 3 online stores and compare them"
  }'
```

**Manager Agent decides**: Route to BROWSER_AGENT
**Result**: Structured comparison with prices, links, availability

---

### Example 2: Desktop Automation

```bash
curl -X POST http://localhost:8000/execute \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Open Visual Studio Code and create a new file called test.py"
  }'
```

**Manager Agent decides**: Route to COMPUTER_USE_AGENT
**Result**: Screenshot showing successful execution

---

### Example 3: Multi-step Workflow

```bash
curl -X POST http://localhost:8000/execute \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Check my Gmail inbox, get unread emails, then save them to a CSV file"
  }'
```

**Manager Agent decides**: 
1. Route to BROWSER_AGENT (fetch Gmail)
2. Route to COMPUTER_USE_AGENT (save CSV)
3. Synthesize results

---

## 🔧 Configuration

### Environment Variables

See `.env.example` for all available options.

**Key Settings**:

```env
# Environment
ENV=development          # development|staging|production
DEBUG=true               # Enable debug logging
LOG_LEVEL=INFO          # INFO|DEBUG|WARNING|ERROR

# Models
DEFAULT_MODEL=gpt-4o    # Default LLM (cheap tasks)
FALLBACK_MODEL=claude-sonnet-4-5  # Fallback (expensive tasks)

# Memory
REDIS_URL=redis://localhost:6379  # Session cache
QDRANT_URL=http://localhost:6333  # Vector storage

# Features
ENABLE_BROWSER_AGENT=true
ENABLE_SOCIAL_AGENT=true
ENABLE_COMPUTER_USE=true
ENABLE_VECTOR_MEMORY=true
```

---

## 📊 Monitoring & Debugging

### Check Service Health

```bash
# All services
curl -s http://localhost:8000/health | jq

# Individual modules
curl http://localhost:8002/health  # Social
curl http://localhost:8003/health  # Browser
curl http://localhost:8004/health  # Computer Use
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f gateway
docker-compose logs -f social
```

### Database Inspection

```bash
# PostgreSQL
docker-compose exec postgres psql -U postgres -d agent_db

# Redis
docker-compose exec redis redis-cli

# Qdrant (Web UI at localhost:6333/dashboard)
```

---

## 🔐 Security Checklist

- [ ] Change `API_SECRET_KEY` in `.env`
- [ ] Store API keys securely (use secret manager in production)
- [ ] Use HTTPS in production
- [ ] Set `ENV=production`
- [ ] Configure CORS origins properly
- [ ] Enable authentication for all endpoints
- [ ] Setup rate limiting
- [ ] Use VPN for computer-use agent
- [ ] Audit webhook signatures (Facebook, Zalo)

---

## 📝 Prompt Engineering Guide

### Manager Agent (Task Classification)

The Manager uses few-shot learning to route tasks. See [orchestrator.py](apps/gateway/orchestrator.py) for examples.

**Best Practices**:
1. Use structured JSON output
2. Include expected output schema
3. Provide 2-3 examples per agent
4. Define task boundaries clearly

### Social Bot Prompts

Customize prompts in:
- `apps/social/facebook.py` → `FACEBOOK_SYSTEM_PROMPT`
- `apps/social/zalo.py` → `ZALO_SYSTEM_PROMPT`

### Browser Agent Instructions

```python
task = BrowserTask(
    url="https://example.com",
    instruction="Extract product names and prices",
    extract_fields=["name", "price", "rating", "url"]
)
```

---

## 🛠️ Development

### Local Development (Without Docker)

```bash
# 1. Setup Python venv
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start services locally
python -m uvicorn apps.gateway.main:app --reload --port 8000

# In separate terminals:
python -m uvicorn apps.social.main:app --port 8002
python -m uvicorn apps.browser.main:app --port 8003
python -m uvicorn apps.computer_use.main:app --port 8004
```

### Database Migrations

When using SQLAlchemy:

```bash
# Create migration
alembic revision --autogenerate -m "add new table"

# Apply migration
alembic upgrade head
```

### Testing

```bash
# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=shared --cov=apps
```

---

## 🚀 Deployment

### Docker Deployment

```bash
# Build all services
docker-compose build

# Push to registry
docker tag agent_gateway:latest your-registry/agent_gateway:latest
docker push your-registry/agent_gateway:latest

# Deploy on server
docker-compose -f docker-compose.prod.yml up -d
```

### Cloud Deployment (AWS/Azure/GCP)

See dedicated deployment guides:
- [AWS Deployment](docs/deployment-aws.md)
- [Azure Deployment](docs/deployment-azure.md)
- [GCP Deployment](docs/deployment-gcp.md)

---

## 🐛 Troubleshooting

### "Connection refused" errors

```bash
# Check if services are running
docker-compose ps

# Restart services
docker-compose restart
```

### LLM API errors

- Verify API keys in `.env`
- Check API rate limits
- Ensure account has sufficient credits

### Browser automation fails

```bash
# Ensure Playwright is installed
pip install browser-use playwright
playwright install chromium
```

### Computer use not working

- Verify `ANTHROPIC_API_KEY` is set
- Check if desktop is accessible
- Try PyAutoGUI fallback

---

## 📚 Documentation

- [Architecture Deep Dive](docs/architecture.md)
- [Multi-Agent Orchestration](docs/orchestration.md)
- [Memory Systems](docs/memory.md)
- [LLM Router Strategy](docs/llm-routing.md)
- [Deployment Guide](docs/deployment.md)

---

## 📦 Dependencies

**Core**:
- `fastapi` - Web framework
- `langchain` / `langgraph` - AI orchestration
- `openai` - GPT-4, embeddings
- `anthropic` - Claude, Computer Use

**Database**:
- `sqlalchemy` - ORM
- `asyncpg` - PostgreSQL driver
- `redis` - Cache
- `qdrant-client` - Vector DB

**Web Automation**:
- `browser-use` - Browser automation
- `playwright` - Browser control
- `beautifulsoup4` - HTML parsing

**Desktop**:
- `pyautogui` - Keyboard/mouse control

See `requirements.txt` for complete list.

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open Pull Request

---

## 📄 License

MIT License - see LICENSE file

---

## 🔮 Roadmap

- [ ] Support for additional LLM providers (Gemini, LLaMA)
- [ ] Advanced memory graphs (Neo4j)
- [ ] Real-time collaboration
- [ ] Web UI dashboard
- [ ] Mobile app
- [ ] Voice input/output
- [ ] Vision capabilities enhancement
- [ ] Custom tool creation interface

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/personal-agent/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/personal-agent/discussions)
- **Email**: support@example.com

---

**Made with ❤️ by the Personal Agent Team**
