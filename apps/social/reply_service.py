"""
Shared reply generation service for social platforms.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from shared.llm import LLMRouter, get_llm_router
from shared.memory import LongTermMemory, get_long_term_memory, get_session_memory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplyProfile:
    """Platform-specific reply policy."""

    platform: str
    namespace: str
    user_metadata_key: str
    system_prompt: str


REPLY_PROFILES = {
    "facebook": ReplyProfile(
        platform="facebook",
        namespace="facebook_context",
        user_metadata_key="sender_id",
        system_prompt="""You are a friendly customer service representative for an online shop.
Always respond in Vietnamese.
- Answer questions about products, pricing, orders, and policies.
- Keep responses concise and professional.
- Do not invent product details.
- If information is missing, say so and offer human support.
- For discount questions, mention current promotions or offer sales support.""",
    ),
    "zalo": ReplyProfile(
        platform="zalo",
        namespace="zalo_context",
        user_metadata_key="user_id",
        system_prompt="""You are a friendly customer service representative for an online shop.
Always respond in Vietnamese.
- Answer questions about products, pricing, orders, and policies.
- Keep responses concise and professional.
- Do not invent product details.
- If information is missing, say so and offer human support.
- For discount questions, mention current promotions or offer sales support.""",
    ),
}


class SocialReplyService:
    """Generate social replies while keeping memory concerns behind one boundary."""

    def __init__(
        self,
        llm_router: Optional[LLMRouter] = None,
        long_term_memory: Optional[LongTermMemory] = None,
    ):
        self.llm_router = llm_router or get_llm_router()
        self.long_term_memory = long_term_memory or get_long_term_memory()

    async def generate_reply(
        self,
        platform: str,
        user_message: str,
        user_id: str,
    ) -> str:
        """Generate a platform-aware reply and persist conversation context."""
        profile = self._get_profile(platform)
        session_memory = get_session_memory(f"{profile.platform}:{user_id}")
        history = await session_memory.get_messages()
        context_text = await self._load_context(profile, user_message)

        messages = [
            {"role": "system", "content": profile.system_prompt + context_text},
            *history,
            {"role": "user", "content": user_message},
        ]

        reply = await self.llm_router.chat(
            messages=messages,
            task="classification",
            temperature=0.7,
            max_tokens=200,
        )

        await session_memory.append("user", user_message)
        await session_memory.append("assistant", reply)
        await self._save_context(profile, user_message, reply, user_id)
        return reply

    async def _load_context(self, profile: ReplyProfile, user_message: str) -> str:
        try:
            context_results = await self.long_term_memory.search(
                query=user_message,
                limit=3,
                namespace=profile.namespace,
            )
        except Exception as exc:
            logger.warning("%s context lookup failed: %s", profile.platform, exc)
            return ""

        if not context_results:
            return ""

        items = "\n".join(f"- {result['text']}" for result in context_results)
        return f"\n\nRelevant context:\n{items}"

    async def _save_context(
        self,
        profile: ReplyProfile,
        user_message: str,
        reply: str,
        user_id: str,
    ) -> None:
        try:
            await self.long_term_memory.save(
                text=f"Q: {user_message}\nA: {reply}",
                metadata={
                    "platform": profile.platform,
                    profile.user_metadata_key: user_id,
                },
                namespace=profile.namespace,
            )
        except Exception as exc:
            logger.warning("%s context save failed: %s", profile.platform, exc)

    @staticmethod
    def _get_profile(platform: str) -> ReplyProfile:
        try:
            return REPLY_PROFILES[platform]
        except KeyError as exc:
            raise ValueError(f"Unsupported social platform: {platform}") from exc


_reply_service: Optional[SocialReplyService] = None


def get_social_reply_service() -> SocialReplyService:
    """Get or create the process-wide social reply service."""
    global _reply_service
    if _reply_service is None:
        _reply_service = SocialReplyService()
    return _reply_service
