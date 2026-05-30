"""
Shared Pydantic models used across modules
"""
from pydantic import BaseModel, Field
from typing import Optional, Any, Literal, TypedDict
from datetime import datetime
from enum import Enum
from uuid import uuid4


class ModuleType(str, Enum):
    """Available modules"""
    COMPUTER_USE = "computer_use"
    BROWSER = "browser"
    SOCIAL = "social"
    
    RAG = "rag"
    AIOPS = "aiops"
    RCA = "rca"
    DEVOPS = "devops"
    EMAIL = "email"
    TOOL = "tool"
    GUARDRAIL = "guardrail"
    REPORT = "report"


class TaskStatus(str, Enum):
    """Task execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ──── Orchestration Models ────

class Task(BaseModel):
    """Single task in execution plan"""
    id: str
    agent: ModuleType
    instruction: str
    expected_output_schema: Optional[dict] = None
    priority: int = 0
    timeout_seconds: int = 300


class ExecutionPlan(BaseModel):
    """Plan created by Manager Agent"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_task: str
    tasks: list[Task]
    estimated_duration_seconds: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TaskResult(BaseModel):
    """Result from completed task"""
    task_id: str
    agent: ModuleType
    status: TaskStatus
    output: Any
    error_message: Optional[str] = None
    execution_time_seconds: float
    completed_at: datetime = Field(default_factory=datetime.utcnow)


class AgentState(TypedDict, total=False):
    """Global state passed through LangGraph"""
    session_id: str
    user_input: str
    allowed_modules: Optional[list[ModuleType]]
    plan: Optional[ExecutionPlan]
    results: dict[str, TaskResult]
    messages: list[dict]
    current_agent: Optional[ModuleType]
    final_answer: Optional[str]
    error: Optional[str]


class ChatMessage(BaseModel):
    """Chat message stored in session memory"""
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ──── Social Platform Models ────

class FacebookMessage(BaseModel):
    """Facebook Messenger message"""
    sender_id: str
    recipient_id: str
    text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ZaloMessage(BaseModel):
    """Zalo message"""
    user_id: str
    oa_id: str
    text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SocialBotReply(BaseModel):
    """Generated reply for social platform"""
    original_message: str
    reply: str
    platform: Literal["facebook", "zalo", "instagram"]
    confidence: float = Field(ge=0, le=1)


# ──── Browser Agent Models ────

class BrowserTask(BaseModel):
    """Task for browser agent"""
    url: Optional[str] = None
    search_query: Optional[str] = None
    instruction: str
    extract_fields: Optional[list[str]] = None


class BrowserResult(BaseModel):
    """Result from browser automation"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    screenshots: Optional[list[str]] = None  # Base64 encoded


# ──── Computer Use Models ────

class ComputerAction(str, Enum):
    """Available computer actions"""
    CLICK = "click"
    TYPE = "type"
    SCREENSHOT = "screenshot"
    SCROLL = "scroll"
    HOTKEY = "hotkey"


class ComputerTask(BaseModel):
    """Task for computer use agent"""
    objective: str
    app_name: Optional[str] = None
    steps: Optional[list[str]] = None


class ComputerResult(BaseModel):
    """Result from computer use"""
    success: bool
    screenshot: Optional[str] = None  # Base64
    output: Optional[str] = None
    error: Optional[str] = None


# ──── API Models ────

class TaskRequest(BaseModel):
    """User request to execute task"""
    user_input: str
    session_id: Optional[str] = None
    modules: Optional[list[ModuleType]] = None


class TaskResponse(BaseModel):
    """Response with task result"""
    status: str
    plan: Optional[ExecutionPlan] = None
    result: Optional[str] = None
    error: Optional[str] = None
    execution_time_seconds: float
