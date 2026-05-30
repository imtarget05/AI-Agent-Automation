"""
LLM Router - route tasks to appropriate models with cost optimization
"""
import litellm
from typing import Optional
from shared.config import get_settings

settings = get_settings()

# Configure litellm
litellm.set_verbose = settings.debug
litellm.telemetry = False  # Disable telemetry in production

# ──── Task-based model routing (cost optimization) ────
TASK_MODEL_MAP = {
    # Cheap models for simple tasks
    "classification": "gpt-4o-mini",     # ~$0.00015 per 1k
    "summarize": "gpt-4o-mini",
    "sentiment": "gpt-4o-mini",
    "parsing": "gpt-4o-mini",
    
    # Mid-tier for reasoning
    "research": "gpt-4o",                 # ~$0.003 per 1k
    "code": "gpt-4o",
    "analysis": "gpt-4o",
    
    # Premium for vision & complex tasks
    "computer_use": "claude-sonnet-4-5",   # Only Claude supports computer-use tool
    "vision": "gpt-4-vision",
    "planning": "gpt-4o",
}


class LLMRouter:
    """Smart LLM router with auto-fallback and cost tracking"""

    def __init__(self):
        self.settings = get_settings()
        self.usage_log = []

    def get_model_for_task(self, task: str) -> str:
        """Get appropriate model for task"""
        task_key = task.lower()
        model = TASK_MODEL_MAP.get(task_key, self.settings.default_model)

        # Route lightweight tasks to Ollama if enabled
        if self.settings.ollama_enabled:
            ollama_tasks = {t.lower() for t in self.settings.ollama_task_types}
            if task_key in ollama_tasks:
                model = f"ollama/{self.settings.ollama_model}"

        return model

    async def chat(
        self,
        messages: list[dict],
        task: str = "research",
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        force_model: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Main chat method with auto-fallback

        Args:
            messages: Conversation history
            task: Task type for model selection
            temperature: Sampling temperature
            max_tokens: Max tokens in response
            **kwargs: Additional LiteLLM parameters

        Returns:
            Response content string
        """
        model = force_model or self.get_model_for_task(task)

        try:
            provider_opts = self._get_provider_options(model)
            api_key = self._get_api_key(model)
            if api_key:
                provider_opts["api_key"] = api_key

            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **provider_opts,
                **kwargs
            )
            return response.choices[0].message.content

        except Exception as e:
            if "overloaded" in str(e).lower() or "rate_limit" in str(e).lower():
                # Fallback to backup model
                if model != self.settings.fallback_model:
                    return await self.chat(
                        messages=messages,
                        task=task,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        force_model=self.settings.fallback_model,
                        **kwargs
                    )
            raise

    async def chat_with_force_model(
        self,
        messages: list[dict],
        force_model: str,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Force specific model (bypass routing)
        """
        return await self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            force_model=force_model,
            **kwargs
        )

    def _get_api_key(self, model: str) -> str:
        """Get API key for model provider"""
        if model.startswith("ollama/"):
            return ""
        if "gpt" in model or "text-embedding" in model:
            return self.settings.openai_api_key
        elif "claude" in model:
            return self.settings.anthropic_api_key
        return ""

    def _get_provider_options(self, model: str) -> dict:
        """Provider-specific options (e.g., api_base for Ollama)"""
        if model.startswith("ollama/"):
            return {"api_base": self.settings.ollama_base_url}
        return {}

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings using OpenAI"""
        if self.settings.embedding_provider.lower() == "ollama" and self.settings.ollama_enabled:
            response = await litellm.aembedding(
                model=f"ollama/{self.settings.ollama_embed_model}",
                input=text,
                api_base=self.settings.ollama_base_url,
            )
        else:
            response = await litellm.aembedding(
                model=self.settings.embedding_model,
                input=text,
                api_key=self.settings.openai_api_key,
            )
        return response.data[0]["embedding"]


# Global instance
_router: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Get or create LLM router instance"""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
