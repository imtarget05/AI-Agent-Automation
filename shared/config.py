"""
Shared configuration loader - tất cả config tập trung ở đây
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """Central configuration"""

    # ──── Environment ────
    env: str = Field(default="development", description="development|staging|production")
    app_name: str = "Personal-AI-Agent"
    app_version: str = "0.1.0"
    debug: bool = Field(default=True)

    # ──── LLM Configuration ────
    openai_api_key: str = Field(default="", description="OpenAI API key")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    default_model: str = Field(default="gpt-4o", description="Default LLM model")
    fallback_model: str = Field(default="claude-sonnet-4-5", description="Fallback model")
    embedding_provider: str = Field(
        default="openai",
        description="Embedding provider: openai|ollama"
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model name"
    )

    # ──── Ollama (Local LLM) ────
    ollama_enabled: bool = Field(default=False, description="Enable Ollama routing")
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL"
    )
    ollama_model: str = Field(
        default="deepseek-r1:8b",
        description="Ollama model name"
    )
    ollama_embed_model: str = Field(
        default="nomic-embed-text",
        description="Ollama embedding model name"
    )
    ollama_task_types: list[str] = Field(
        default=["classification", "summarize", "parsing"],
        description="Tasks routed to Ollama when enabled"
    )

    # ──── Database ────
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:password@localhost:5432/agent_db",
        description="PostgreSQL connection string"
    )
    monitoring_database_url: str = Field(
        default="sqlite:///./metrics.db",
        description="Synchronous SQLAlchemy URL for monitoring metrics",
    )
    redis_url: str = Field(default="redis://localhost:6379", description="Redis connection")
    qdrant_url: str = Field(default="http://localhost:6333", description="Qdrant vector DB")

    # ──── Social Platforms ────
    fb_page_token: str = Field(default="", description="Facebook Page Access Token")
    fb_verify_token: str = Field(default="my_webhook_secret", description="Facebook webhook verify token")
    fb_app_secret: str = Field(default="", description="Facebook app secret for webhook signatures")
    zalo_oa_token: str = Field(default="", description="Zalo OA access token")
    zalo_server_key: str = Field(default="", description="Zalo server key")
    insta_business_account_id: Optional[str] = None

    # ──── Security ────
    api_secret_key: str = Field(default="change-me-in-production", description="Secret key for JWT")
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        description="CORS allowed origins"
    )

    # ──── Observability ────
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "personal-agent"
    log_level: str = "INFO"

    # ──── Service URLs ────
    browser_service_url: str = Field(
        default="http://browser:8003",
        description="Browser agent service URL"
    )
    computer_use_service_url: str = Field(
        default="http://computer_use:8004",
        description="Computer use agent service URL"
    )
    social_service_url: str = Field(
        default="http://social:8002",
        description="Social agent service URL"
    )
    rag_service_url: str = Field(
        default="http://rag_service:8007",
        description="RAG service URL"
    )
    agent_http_timeout_seconds: int = Field(
        default=60,
        description="Timeout for agent HTTP requests"
    )

    # ──── RAG Configuration ────
    rag_collection: str = Field(
        default="rag_documents",
        description="Qdrant collection for RAG"
    )
    rag_chunk_size: int = Field(default=800, description="RAG chunk size (chars)")
    rag_chunk_overlap: int = Field(default=100, description="RAG chunk overlap (chars)")
    rag_default_top_k: int = Field(default=5, description="Default top-k for retrieval")
    rag_docs_path: str = Field(default="docs", description="Default docs path for RAG")

    # ──── Feature Flags ────
    enable_browser_agent: bool = True
    enable_social_agent: bool = True
    enable_computer_use: bool = True
    enable_vector_memory: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


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
