"""
Shared configuration loader - tất cả config tập trung ở đây
"""

from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from functools import lru_cache
from typing import Optional, Any
import os


PLACEHOLDER_SECRETS = frozenset(
    {
        "change-me",
        "change-me-in-production",
        "dev-secret-key-change-in-prod",
        "dev-internal-service-token-change-in-prod",
        "dev-qdrant-key-change-in-prod",
        "dev-postgres-password-change-in-prod",
        "dev-redis-password-change-in-prod",
        "replace-me",
        "sk-...",
        "sk-ant-...",
        "your-api-key",
        "your-slack-signing-secret",
        "your-super-secret-key-change-this",
        "my_webhook_secret",
        "postgres_password",
        "your_api_key",
    }
)


def _is_placeholder_secret(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized in PLACEHOLDER_SECRETS
        or "placeholder" in normalized
        or normalized.startswith("your-")
        or normalized.startswith("your_")
        or (normalized.startswith("sk-") and len(normalized) < 10)
    )


def _is_localhost(url: str) -> bool:
    return "localhost" in url.lower() or "127.0.0.1" in url


class Settings(BaseSettings):
    """Central configuration"""

    def __init__(self, **values: Any) -> None:
        # Keep explicit _env_file=None constructors isolated from SDKs that may
        # eagerly copy local .env values into os.environ during the same process.
        if (
            values.get("_env_file") is None
            and str(values.get("env", "")).lower() == "production"
        ):
            values.setdefault("sandbox_demo_mode", False)
            for field_name, default_value in {
                "fb_page_token": "",
                "fb_verify_token": "my_webhook_secret",
                "fb_app_secret": "",
                "zalo_oa_token": "",
                "zalo_server_key": "",
                "telegram_bot_token": "",
                "telegram_webhook_secret": "",
                "slack_bot_token": "",
                "slack_signing_secret": "",
            }.items():
                values.setdefault(field_name, default_value)
        super().__init__(**values)

    # ──── Environment ────
    env: str = Field(
        default="development", description="development|staging|production"
    )
    app_name: str = "Personal-AI-Agent"
    app_version: str = "0.1.0"
    debug: bool = Field(default=True)
    sandbox_demo_mode: bool = Field(
        default=False,
        description="Return clearly labeled mock LLM responses in local demos only",
    )

    # ──── LLM Configuration ────
    openai_api_key: str = Field(default="", description="OpenAI API key")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    gemini_api_key: str = Field(default="", description="Gemini API key")
    openrouter_api_key: str = Field(default="", description="OpenRouter API key")
    default_model: str = Field(default="gpt-4o", description="Default LLM model")
    reasoning_model: str = Field(
        default="", description="Reasoning model for complex tasks"
    )
    fallback_model: str = Field(
        default="claude-sonnet-4-5", description="Fallback model"
    )
    embedding_provider: str = Field(
        default="openai", description="Embedding provider: openai|ollama"
    )
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Embedding model name"
    )

    # ──── Ollama (Local LLM) ────
    ollama_enabled: bool = Field(default=False, description="Enable Ollama routing")
    ollama_base_url: str = Field(
        default="http://localhost:11434", description="Ollama API base URL"
    )
    ollama_model: str = Field(default="deepseek-r1:8b", description="Ollama model name")
    ollama_embed_model: str = Field(
        default="nomic-embed-text", description="Ollama embedding model name"
    )
    ollama_task_types: list[str] = Field(
        default=["classification", "summarize", "parsing", "draft", "report_draft"],
        description="Tasks routed to Ollama when enabled",
    )

    # ──── Database ────
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:password@localhost:5432/agent_db",
        description="PostgreSQL connection string",
    )
    monitoring_database_url: str = Field(
        default="sqlite:///./metrics.db",
        description="Synchronous SQLAlchemy URL for monitoring metrics",
    )
    redis_url: str = Field(
        default="redis://localhost:6379", description="Redis connection"
    )
    qdrant_url: str = Field(
        default="http://localhost:6333", description="Qdrant vector DB"
    )
    qdrant_api_key: str = Field(default="", description="Qdrant API key")

    # ──── Social Platforms ────
    fb_page_token: str = Field(default="", description="Facebook Page Access Token")
    fb_verify_token: str = Field(
        default="my_webhook_secret", description="Facebook webhook verify token"
    )
    fb_app_secret: str = Field(
        default="", description="Facebook app secret for webhook signatures"
    )
    zalo_oa_token: str = Field(default="", description="Zalo OA access token")
    zalo_server_key: str = Field(default="", description="Zalo server key")
    telegram_bot_token: str = Field(default="", description="Telegram Bot Token")
    telegram_webhook_secret: str = Field(
        default="", description="Telegram webhook verification secret"
    )
    slack_bot_token: str = Field(default="", description="Slack Bot OAuth Token")
    slack_signing_secret: str = Field(
        default="", description="Slack Request Signing Secret"
    )
    insta_business_account_id: Optional[str] = None

    # ──── Security ────
    api_secret_key: str = Field(
        default="change-me-in-production", description="Secret key for JWT"
    )
    internal_service_token: str = Field(
        default="change-me-in-production",
        description="Shared token for service-to-service HTTP authentication",
    )
    cors_origins: list[str] = Field(
        default=["*"],
        description="CORS allowed origins",
    )
    dashboard_gateway_url: str = Field(
        default="http://localhost:8000",
        description="Public Gateway URL for the dashboard browser client",
    )

    # ──── Observability ────
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "personal-agent"
    log_level: str = "INFO"
    prometheus_url: str = Field(
        default="http://localhost:9090", description="Prometheus base URL"
    )

    # ---- Email ----
    smtp_server: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_drafts_path: str = "docs"

    # ──── Service URLs ────
    browser_service_url: str = Field(
        default="http://browser:8003", description="Browser agent service URL"
    )
    computer_use_service_url: str = Field(
        default="http://computer_use:8004", description="Computer use agent service URL"
    )
    social_service_url: str = Field(
        default="http://social:8002", description="Social agent service URL"
    )
    gateway_service_url: str = Field(
        default="http://gateway:8000", description="Gateway service URL"
    )
    rag_service_url: str = Field(
        default="http://rag_service:8007", description="RAG service URL"
    )
    tool_service_url: str = Field(
        default="http://tool_service:8008", description="Tool registry service URL"
    )
    email_agent_service_url: str = Field(
        default="http://email_agent:8009", description="Email agent service URL"
    )
    guardrail_service_url: str = Field(
        default="http://guardrail_service:8010", description="Guardrail service URL"
    )
    monitoring_service_url: str = Field(
        default="http://monitoring:8005", description="Monitoring service URL"
    )
    approval_service_url: str = Field(
        default="http://approval_service:8011", description="Approval service URL"
    )
    report_agent_service_url: str = Field(
        default="http://report_agent:8012", description="Report agent service URL"
    )
    aiops_agent_service_url: str = Field(
        default="http://aiops_agent:8013", description="AIOps agent service URL"
    )
    rca_agent_service_url: str = Field(
        default="http://rca_agent:8014", description="RCA agent service URL"
    )
    devops_agent_service_url: str = Field(
        default="http://devops_agent:8015", description="DevOps agent service URL"
    )
    agentscope_agent_service_url: str = Field(
        default="http://agentscope_agent:8017", description="AgentScope agent service URL"
    )
    agent_http_timeout_seconds: int = Field(
        default=60, description="Timeout for agent HTTP requests"
    )

    # ──── RAG Configuration ────
    rag_collection: str = Field(
        default="rag_documents", description="Qdrant collection for RAG"
    )
    rag_chunk_size: int = Field(default=800, description="RAG chunk size (chars)")
    rag_chunk_overlap: int = Field(default=100, description="RAG chunk overlap (chars)")
    rag_default_top_k: int = Field(default=5, description="Default top-k for retrieval")
    rag_docs_path: str = Field(default="docs", description="Default docs path for RAG")

    # ---- Accuracy & Verification (Corrective RAG) ----
    rag_verification_enabled: bool = Field(
        default=True, description="Enable LLM-based grading of retrieved documents"
    )
    rag_grading_threshold: float = Field(
        default=0.7, description="Threshold for document relevance grading"
    )
    rca_max_reasoning_steps: int = Field(
        default=5, description="Maximum reasoning steps for the RCA agent"
    )
    accuracy_guardrail_enabled: bool = Field(
        default=True, description="Enable final synthesis accuracy check"
    )
    orchestrator_max_iterations: int = Field(
        default=8, ge=1, description="Maximum supervisor decisions per request"
    )

    # ──── MCP Configuration ────
    mcp_enabled: bool = Field(
        default=True, description="Enable optional MCP server integrations"
    )
    mcp_servers: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Opt-in STDIO MCP servers registered on Gateway startup",
    )

    # ---- Optional Open-source Runtime Adapters ----
    agentscope_enabled: bool = Field(
        default=False,
        description="Enable the optional AgentScope 2.0 remote agent",
    )
    claw_enabled: bool = Field(
        default=False,
        description="Enable the optional claw-code CLI adapter",
    )
    claw_binary_path: Optional[str] = Field(
        default=None,
        description="Explicit path to the claw binary; defaults to local build or PATH",
    )
    claw_working_directory: Optional[str] = Field(
        default=None,
        description="Working directory used by claw-code CLI tasks",
    )
    claw_timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="Maximum runtime for one claw-code CLI invocation",
    )

    # ──── Open-source Knowledge Seeding ────
    open_source_seed_enabled: bool = Field(
        default=True,
        description="Seed curated local open-source docs into vector memory",
    )
    open_source_seed_background: bool = Field(
        default=True,
        description="Run open-source seeding in the background during startup",
    )
    open_source_seed_force: bool = Field(
        default=False,
        description="Force re-embedding even when local docs are unchanged",
    )

    # ──── OpenTelemetry ────
    otel_enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry distributed tracing",
    )
    otel_service_name: str = Field(
        default="ai-agent-automation",
        description="Service name injected into every span",
    )
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317",
        description="OTLP gRPC/HTTP endpoint for span export",
    )
    otel_traces_exporter: str = Field(
        default="otlp",
        description="Span exporter: otlp | jaeger | console",
    )
    otel_log_level: str = Field(
        default="INFO",
        description="Log level used by the OTel SDK",
    )

    # ──── Token Budget ────
    max_tokens_per_request: int = Field(
        default=20000,
        description="Hard token limit per single LLM request",
    )
    max_tokens_per_workflow: int = Field(
        default=80000,
        description="Cumulative token limit per workflow run",
    )
    max_llm_calls_per_workflow: int = Field(
        default=20,
        description="Maximum number of LLM calls in a single workflow",
    )
    max_cost_per_workflow_usd: float = Field(
        default=2.00,
        description="Maximum estimated USD cost per workflow",
    )
    max_cost_per_user_daily_usd: float = Field(
        default=10.00,
        description="Maximum estimated USD cost per user per day",
    )

    # ──── Feature Flags ────
    enable_browser_agent: bool = True
    enable_social_agent: bool = True
    enable_computer_use: bool = True
    enable_vector_memory: bool = True

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.env.lower() != "production":
            return self

        if _is_placeholder_secret(self.api_secret_key):
            raise ValueError(
                "API_SECRET_KEY must be set to a non-placeholder value in production"
            )
        if _is_placeholder_secret(self.internal_service_token):
            raise ValueError(
                "INTERNAL_SERVICE_TOKEN must be set to a non-placeholder value "
                "in production"
            )
        if _is_placeholder_secret(self.qdrant_api_key):
            raise ValueError(
                "QDRANT_API_KEY must be set to a non-placeholder value in production"
            )
        if "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS cannot contain '*' in production")
        if self.sandbox_demo_mode:
            raise ValueError("SANDBOX_DEMO_MODE cannot be enabled in production")

        slack_configured = bool(self.slack_bot_token or self.slack_signing_secret)
        if slack_configured and _is_placeholder_secret(self.slack_signing_secret):
            raise ValueError(
                "SLACK_SIGNING_SECRET must be set to a non-placeholder value "
                "when Slack is configured in production"
            )
        if self.fb_page_token:
            if _is_placeholder_secret(self.fb_verify_token):
                raise ValueError(
                    "FB_VERIFY_TOKEN must be set to a non-placeholder value "
                    "when Facebook is configured in production"
                )
            if _is_placeholder_secret(self.fb_app_secret):
                raise ValueError(
                    "FB_APP_SECRET must be set to a non-placeholder value "
                    "when Facebook is configured in production"
                )
        if self.zalo_oa_token and _is_placeholder_secret(self.zalo_server_key):
            raise ValueError(
                "ZALO_SERVER_KEY must be set to a non-placeholder value "
                "when Zalo is configured in production"
            )
        if self.telegram_bot_token and _is_placeholder_secret(
            self.telegram_webhook_secret
        ):
            raise ValueError(
                "TELEGRAM_WEBHOOK_SECRET must be set to a non-placeholder value "
                "when Telegram is configured in production"
            )

        has_cloud_llm = any(
            not _is_placeholder_secret(api_key)
            for api_key in (self.openai_api_key, self.anthropic_api_key)
        )
        if not self.ollama_enabled and not has_cloud_llm:
            raise ValueError(
                "At least one usable LLM provider must be configured in production"
            )

        # Ensure internal service URLs don't point to localhost in production
        service_urls = [
            self.gateway_service_url,
            self.rag_service_url,
            self.tool_service_url,
            self.guardrail_service_url,
            self.monitoring_service_url,
            self.approval_service_url,
        ]
        for url in service_urls:
            if _is_localhost(url):
                raise ValueError(
                    f"Service URL '{url}' cannot point to localhost in production. "
                    "Use container names or internal load balancer addresses."
                )

        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


def get_database_url() -> str:
    """Get database URL"""
    return get_settings().database_url


def get_redis_url() -> str:
    """Get Redis URL"""
    return get_settings().redis_url


def get_bind_host() -> str:
    """Return the bind host for uvicorn.

    Use the `BIND_HOST` environment variable to control the bind address
    (for example set to a public bind address in containerized deployments).
    Defaults to localhost (127.0.0.1) to satisfy CI security scanners which
    flag hardcoded "bind all" literals in source.
    """
    return os.getenv("BIND_HOST", "127.0.0.1")
