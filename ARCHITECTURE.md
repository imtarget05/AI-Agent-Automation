# Architecture Documentation - Personal AI Agent Platform

## 🎯 System Design Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER / CLIENT                                │
│        (curl, API client, ChatUI, Webhook from FB/Zalo)            │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────────┐
        │                            │                                │
        ▼                            ▼                                ▼
┌─────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│   FastAPI       │      │  FB Webhook      │      │  Zalo Webhook   │
│   Gateway       │      │  /social/facebook│      │  /social/zalo    │
│  Port 8000      │      │  Port 8002       │      │  Port 8002       │
└────────┬────────┘      └──────────┬───────┘      └────────┬─────────┘
         │                          │                        │
         └──────────────────────────┼────────────────────────┘
                                    │
        ┌───────────────────────────▼───────────────────────────┐
        │                                                       │
        │         SHARED INFRASTRUCTURE                        │
        │  ┌──────────┐  ┌──────────┐  ┌────────────┐        │
        │  │ LLM      │  │ Memory   │  │ Models &   │        │
        │  │ Router   │  │ (Long+   │  │ Schemas    │        │
        │  │ (Lite    │  │ Short)   │  │ (Pydantic) │        │
        │  │ LLM)     │  │ (Vector+ │  │            │        │
        │  │          │  │ Session) │  │            │        │
        │  └──────────┘  └──────────┘  └────────────┘        │
        │                                                       │
        └────────┬──────────────────────────────────┬──────────┘
                 │                                  │
        ┌────────▼────────┐              ┌─────────▼─────────┐
        │                 │              │                   │
        │  LangGraph      │              │  Session Memory   │
        │  Orchestrator   │              │  (Session context)│
        │  (Manager Agent)│              │                   │
        │                 │              │                   │
        └────────┬────────┘              └─────────────────┘
                 │
        ┌────────┴────────────┬─────────────────┬──────────────┐
        │                     │                 │              │
        ▼                     ▼                 ▼              ▼
    ┌────────┐            ┌────────┐        ┌──────┐      ┌──────────┐
    │Computer│            │Browser │        │Social│      │Synthesiz│
    │Use Node│            │Node    │        │Node  │      │Node      │
    │        │            │        │        │      │      │          │
    │8004    │            │8003    │        │8002  │      │(local)   │
    └───┬────┘            └───┬────┘        └──┬───┘      └──────────┘
        │                     │                │
        └─────────────────────┼────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
            ▼                 ▼                 ▼
        ┌────────┐      ┌─────────┐      ┌──────────┐
        │OpenAI  │      │Anthropic│      │Qdrant    │
        │GPT-4o  │      │Claude   │      │Vector DB │
        │        │      │         │      │          │
        └────────┘      └─────────┘      └──────────┘
            │                 │                 │
            └─────────────────┴─────────────────┘
                              │
            ┌─────────────────┴─────────────────┐
            │                                   │
            ▼                                   ▼
        ┌────────┐                       ┌──────────┐
        │External│                       │Your Data │
        │APIs    │                       │Storage   │
        │(Web)   │                       │(Vector)  │
        └────────┘                       └──────────┘
```

---

## 📦 Component Details

### 1. FastAPI Gateway (Port 8000)

**Location**: `apps/gateway/main.py`

**Responsibilities**:
- Accept user requests
- Validate API keys
- Route requests to orchestrator
- Manage sessions
- Return structured responses

**Key Endpoints**:
```
POST /execute              - Synchronous task execution
POST /execute-async        - Asynchronous task execution
GET /task-status/{id}      - Check async task status
POST /session              - Create new session
GET /session/{id}/history  - Get conversation history
GET /health                - Health check
```

**Authentication**: 
- Bearer token via `X-API-Key` header

---

### 2. LangGraph Orchestrator

**Location**: `apps/gateway/orchestrator.py`

**Workflow**:

```
START
  │
  ▼
┌─────────────┐
│   MANAGER   │  ← Analyzes request
│   NODE      │    Creates execution plan
└──────┬──────┘    Routes to agents
       │
       ├─→ TASK_TYPE = COMPUTER_USE?
       │     ▼
       │   ┌──────────────────┐
       │   │ COMPUTER_USE     │  ← Takes screenshots
       │   │ NODE             │    Clicks, types, etc
       │   └────────┬─────────┘
       │            │
       ├─→ TASK_TYPE = BROWSER?
       │     ▼
       │   ┌──────────────────┐
       │   │ BROWSER          │  ← Scrapes web
       │   │ NODE             │    Extracts data
       │   └────────┬─────────┘
       │            │
       └─→ TASK_TYPE = SOCIAL?
             ▼
           ┌──────────────────┐
           │ SOCIAL           │  ← Generates replies
           │ NODE             │    Context-aware
           └────────┬─────────┘
                    │
                    ▼
              ┌──────────────┐
              │  SYNTHESIZE  │  ← Combines results
              │  NODE        │    Creates final answer
              └──────┬───────┘
                     │
                     ▼
                    END
```

**State Flow**:
```python
AgentState = {
    "session_id": str,
    "user_input": str,
    "plan": ExecutionPlan,          # Created by Manager
    "results": {task_id: result},   # Filled by agents
    "messages": list,               # Conversation history
    "final_answer": str,            # Generated by Synthesizer
}
```

---

### 3. Shared Infrastructure

#### 3.1 LLM Router (`shared/llm.py`)

**Smart model selection**:
```python
TASK_MODEL_MAP = {
    "classification": "gpt-4o-mini",      # Cheap
    "summarize": "gpt-4o-mini",
    "research": "gpt-4o",                 # Balanced
    "code": "gpt-4o",
    "computer_use": "claude-sonnet-4-5",  # Expensive, special tool
}
```

**Cost Optimization**:
- Route simple tasks to cheaper models
- Fallback to expensive models when needed
- Track usage for cost analysis

#### 3.2 Memory Layer (`shared/memory.py`)

**Long-term Memory** (Qdrant Vector DB):
- Store facts with embeddings
- Semantic search for relevant context
- Persistent across sessions
- Used by all agents

**Session Memory** (Redis):
- Conversation history per user
- 24-hour TTL
- Fast access
- Real-time updates

```
User: "I'm interested in iPhones"
LongTerm: Save → "User.interests = ['iPhones']"
Session: Save → [{"role": "user", "content": "..."}]

Next message:
Browser: Search context + previous interests
Social: Generate reply with personality continuity
```

#### 3.3 Models (`shared/models.py`)

**Pydantic Schemas for Type Safety**:
```python
TaskRequest          # User input
ExecutionPlan        # Manager output
TaskResult           # Agent execution result
AgentState          # Internal state
FacebookMessage     # Social webhook
BrowserTask         # Browser instruction
ComputerTask        # Desktop instruction
```

---

### 4. Social Media Module (Port 8002)

**Architecture**:

```
┌─────────────────────────────────────────┐
│     Social Media Module (Port 8002)    │
│                                         │
│  ┌──────────────────────────────────┐ │
│  │   FastAPI App (main.py)          │ │
│  │   - Health checks                 │ │
│  │   - Webhook routing               │ │
│  │   - Error handling                │ │
│  └────────┬──────────────────────┬──┘ │
│           │                      │     │
│  ┌────────▼──────┐    ┌─────────▼──┐ │
│  │  FACEBOOK.PY  │    │  ZALO.PY   │ │
│  │                │    │            │ │
│  │ • Webhook GET  │    │ • Webhook  │ │
│  │ • Webhook POST │    │   POST     │ │
│  │ • Signature    │    │ • Signature│ │
│  │   verify       │    │   verify   │ │
│  │ • Gen reply    │    │ • Gen reply│ │
│  │ • Send message │    │ • Send msg │ │
│  │ • Save context │    │ • Save ctx │ │
│  └────────┬───────┘    └────────┬───┘ │
│           │                      │     │
│           └──────────┬───────────┘     │
│                      │                 │
│           ┌──────────▼──────────┐     │
│           │  LLM Router         │     │
│           │  Memory Layer       │     │
│           │  (Shared)           │     │
│           └─────────────────────┘     │
└─────────────────────────────────────────┘
```

**Request Flow**:
```
1. Facebook sends webhook
   POST /social/facebook/webhook
   Body: {
     "entry": [{
       "messaging": [{
         "sender": {"id": "123"},
         "message": {"text": "Hi, do you have iPhone?"}
       }]
     }]
   }

2. Handler extracts message
   sender_id = "123"
   text = "Hi, do you have iPhone?"

3. Generate reply
   - Get session memory (user context)
   - Get long-term memory (user history)
   - Call LLM with FACEBOOK_SYSTEM_PROMPT
   - Generate response

4. Send reply back
   POST https://graph.facebook.com/v18.0/me/messages
   {
     "recipient": {"id": "123"},
     "message": {"text": "We have iPhone 15 Pro..."}
   }

5. Save to memory
   - Session: Append user + bot message
   - Long-term: Save Q&A for context
```

---

### 5. Browser Agent (Port 8003)

**Capabilities**:

```
┌──────────────────────────┐
│  Browser Agent (8003)    │
├──────────────────────────┤
│                          │
│ PRIMARY: browser-use lib │
│ ├─ Claude vision         │
│ ├─ DOM interaction       │
│ └─ Screenshot analysis   │
│                          │
│ FALLBACK: httpx + BS4   │
│ ├─ HTTP requests         │
│ ├─ HTML parsing          │
│ └─ CSS selectors         │
│                          │
└──────────────────────────┘
```

**Task Processing**:
```python
1. Task Input:
   BrowserTask(
       url="https://shopee.vn/search?q=iphone",
       instruction="Extract product names and prices",
       extract_fields=["name", "price", "rating", "url"]
   )

2. If browser-use available:
   a. Create agent with Claude 3.5 Sonnet
   b. Agent navigates to URL
   c. Agent reads page content
   d. Agent extracts structured data
   e. Agent returns JSON

3. Else (fallback):
   a. Fetch HTML via httpx
   b. Parse with BeautifulSoup
   c. Use CSS selectors to find items
   d. Extract text/attributes
   e. Return as JSON

4. Output:
   BrowserResult(
       success=true,
       data=[
           {"name": "iPhone 15 Pro", "price": "29M", ...},
           ...
       ]
   )
```

---

### 6. Computer Use Agent (Port 8004)

**Dual Implementation**:

```
┌────────────────────────────────────────────┐
│      Computer Use Agent (8004)             │
├────────────────────────────────────────────┤
│                                            │
│  PRIMARY: Anthropic Computer Use API      │
│  ├─ Model: Claude 3.5 Sonnet              │
│  ├─ Capabilities:                         │
│  │  ├─ Take screenshots                   │
│  │  ├─ Click coordinates                  │
│  │  ├─ Type text                          │
│  │  ├─ Press keys                         │
│  │  └─ Vision-based navigation            │
│  │                                        │
│  │ FALLBACK: PyAutoGUI                    │
│  ├─ Lightweight                           │
│  ├─ No API required                       │
│  ├─ Local execution only                  │
│  └─ Manual step parsing                   │
│                                            │
└────────────────────────────────────────────┘
```

**Execution Loop**:
```
USER REQUEST: "Open Chrome and go to gmail.com"
    │
    ▼
TASK PARSING:
    objective: "Open Chrome and navigate to gmail.com"
    app_name: "Chrome"
    steps: ["hotkey win", "type chrome", "hotkey return", ...]
    │
    ▼
TRY ANTHROPIC COMPUTER USE:
    ├─ Take screenshot
    ├─ Analyze desktop state
    ├─ Determine action
    ├─ Execute action
    ├─ Take screenshot
    └─ Repeat until done
    │
    ▼ (if error)
FALLBACK TO PYAUTOGUI:
    ├─ Execute steps sequentially
    ├─ Screenshot before/after
    └─ Return logs
    │
    ▼
RESULT:
    {
      "success": true,
      "screenshot": "base64...",
      "output": "Chrome opened successfully"
    }
```

---

## 🔄 Data Flow Examples

### Example 1: Simple Web Research

```
USER INPUT:
  "Find iPhone 15 prices on Shopee"
    │
    ▼ (HTTP POST to Gateway)
┌─────────────────────────────────┐
│ Gateway receives request         │
│ Creates session_id               │
│ Routes to orchestrator           │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ Manager Agent analyzes           │
│ "This is web research task"      │
│ Routes to: BROWSER_AGENT         │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ Browser Agent                    │
│ ├─ Navigate to Shopee            │
│ ├─ Search for "iPhone 15"        │
│ └─ Extract products              │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ Synthesizer combines results     │
│ Creates final response:          │
│ "Found 5 iPhone 15 options..."   │
└─────────────────────────────────┘
    │
    ▼
    Response back to user
```

### Example 2: Social Media Auto-Reply

```
FACEBOOK SENDS WEBHOOK:
  POST /social/facebook/webhook
  {
    "sender": {"id": "user123"},
    "message": {"text": "Do you have iPhone in stock?"}
  }
    │
    ▼
┌─────────────────────────────────┐
│ Handler extracts message        │
│ sender_id = "user123"            │
│ text = "Do you have iPhone...?"  │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ Get context                      │
│ ├─ Session memory (history)     │
│ ├─ Long-term memory (context)   │
│ └─ Previous messages             │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ Call LLM                         │
│ System: FACEBOOK_SYSTEM_PROMPT   │
│ Messages: [history + new msg]    │
│ Generate: Reply text             │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ Send reply back to Facebook      │
│ POST to graph.facebook.com/...   │
│ Message: "Yes, we have..."       │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ Save to memory                   │
│ ├─ Session: user+bot exchange    │
│ └─ Long-term: Q&A for context    │
└─────────────────────────────────┘
```

---

## 🗄️ Database Schema Overview

### PostgreSQL (User data, audit logs)
```
agent_db/
├── users
│   ├── id
│   ├── name
│   ├── email
│   └── created_at
├── sessions
│   ├── id (UUID)
│   ├── user_id
│   ├── started_at
│   └── ended_at
└── audit_logs
    ├── id
    ├── action
    ├── timestamp
    └── details
```

### Redis (Session cache, TTL 24h)
```
session:user123 = [
    {"role": "user", "content": "...", "timestamp": "..."},
    {"role": "assistant", "content": "...", "timestamp": "..."},
    ...
]

# Auto-expires after 24 hours
```

### Qdrant (Vector memory)
```
agent_memory collection:
├── id: UUID
├── vector: [1536 dimensions]  # text-embedding-3-small
├── payload: {
│   ├── text: "Q: ... A: ..."
│   ├── namespace: "facebook_context|zalo_context|general"
│   ├── created_at: timestamp
│   └── metadata: {...}
└── score: similarity
```

---

## 🔐 Security Architecture

```
┌────────────────┐
│  Client/User   │
└────────┬───────┘
         │
         ├─ HTTPS (in production)
         ├─ X-API-Key header
         │
         ▼
┌──────────────────────────────────┐
│  API Gateway (FastAPI)           │
│                                  │
│  ├─ Input validation             │
│  ├─ Rate limiting                │
│  ├─ CORS checking                │
│  └─ Request logging              │
└────────┬─────────────────────────┘
         │
         ├─ Verify signatures (FB/Zalo webhooks)
         ├─ Sanitize inputs
         ├─ Mask sensitive data
         │
         ▼
┌──────────────────────────────────┐
│  Orchestrator & Agents           │
│                                  │
│  ├─ API keys in environment      │
│  ├─ No credentials in code       │
│  ├─ Audit logging                │
│  └─ Error handling               │
└────────┬─────────────────────────┘
         │
         ├─ Database SSL
         ├─ Redis auth
         ├─ Qdrant API key
         │
         ▼
┌──────────────────────────────────┐
│  External Services               │
│  - OpenAI API                    │
│  - Anthropic API                 │
│  - Facebook Graph API            │
│  - Zalo API                      │
└──────────────────────────────────┘
```

---

## 📊 Request/Response Lifecycle

```
TIMING: ~3-5 seconds for typical request

┌──────────────┬────────────────────────────────────────┐
│ Phase        │ Duration                               │
├──────────────┼────────────────────────────────────────┤
│ Request      │ 10ms   (network)                       │
│ Manager Plan │ 1s     (LLM call)                      │
│ Execution    │ 2-5s   (browser, computer, etc)        │
│ Synthesis    │ 500ms  (LLM call)                      │
│ Response     │ 10ms   (network)                       │
└──────────────┴────────────────────────────────────────┘
```

---

## 🚀 Deployment Architecture

### Local Development
- Single docker-compose.yml
- All services on localhost
- SQLite for quick testing

### Production
- Kubernetes orchestration
- Separate service replicas
- CDN for static assets
- Load balancer for gateway
- Database replication
- Redis cluster
- Qdrant sharding

---

## 📈 Scalability Considerations

1. **Gateway Scaling**: Add more API server replicas behind load balancer
2. **Agent Scaling**: Deploy agents to separate machines
3. **Database Scaling**: PostgreSQL replication, Redis cluster
4. **Vector DB**: Qdrant sharding across multiple nodes
5. **API Rate Limiting**: Implement per-user quotas
6. **Async Processing**: Use task queues (Celery, RQ) for long tasks

---

**Last Updated**: May 30, 2026
**Version**: 0.1.0
