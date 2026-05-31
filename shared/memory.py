"""
Memory layer - Long-term (vector) + Short-term (session) memory
"""

import json
import uuid
from typing import Optional
from datetime import datetime
import asyncio

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import redis.asyncio as aioredis

from shared.config import get_settings
from shared.llm import get_llm_router
from shared.models import ChatMessage

settings = get_settings()


class LongTermMemory:
    """Vector-based memory using Qdrant"""

    COLLECTION = "agent_memory"

    def __init__(self):
        self.client = AsyncQdrantClient(url=settings.qdrant_url)
        self.router = get_llm_router()
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def init(self):
        """Initialize Qdrant collection"""
        try:
            await self.client.get_collection(self.COLLECTION)
        except Exception:
            sample_vector = await self.router.embed("init")
            vector_size = len(sample_vector)
            await self.client.create_collection(
                self.COLLECTION,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
        self._initialized = True

    async def _ensure_initialized(self):
        """Ensure Qdrant collection exists before use"""
        if self._initialized:
            return
        async with self._init_lock:
            if not self._initialized:
                await self.init()

    async def save(
        self, text: str, metadata: Optional[dict] = None, namespace: str = "general"
    ) -> str:
        """
        Save memory with embedding

        Args:
            text: Content to remember
            metadata: Additional metadata
            namespace: Memory namespace/category

        Returns:
            Memory ID
        """
        await self._ensure_initialized()
        vector = await self.router.embed(text)
        point_id = str(uuid.uuid4())

        payload = {
            "text": text,
            "namespace": namespace,
            "created_at": datetime.utcnow().isoformat(),
            **(metadata or {}),
        }

        await self.client.upsert(
            self.COLLECTION,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )
        return point_id

    async def search(
        self,
        query: str,
        limit: int = 5,
        namespace: Optional[str] = None,
        score_threshold: float = 0.5,
    ) -> list[dict]:
        """
        Search memories by similarity

        Args:
            query: Search query
            limit: Number of results
            namespace: Filter by namespace
            score_threshold: Minimum similarity score

        Returns:
            List of relevant memories with scores
        """
        await self._ensure_initialized()
        query_vector = await self.router.embed(query)

        results = await self.client.search(
            self.COLLECTION,
            query_vector=query_vector,
            limit=limit,
            query_filter={"must": [{"key": "namespace", "match": {"value": namespace}}]}
            if namespace
            else None,
            score_threshold=score_threshold,
        )

        return [
            {
                "id": r.id,
                "text": r.payload.get("text"),
                "score": r.score,
                "metadata": {k: v for k, v in r.payload.items() if k != "text"},
            }
            for r in results
        ]

    async def delete(self, memory_id: str):
        """Delete a memory by ID"""
        await self.client.delete(
            self.COLLECTION, points_selector={"points": [memory_id]}
        )


class SessionMemory:
    """Short-term memory using Redis (24h TTL)"""

    TTL = 86400  # 24 hours

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.key = f"session:{session_id}"

    async def _get_redis(self) -> aioredis.Redis:
        """Get Redis connection"""
        return await aioredis.from_url(settings.redis_url, decode_responses=True)

    async def append(self, role: str, content: str):
        """Append message to session history"""
        redis = await self._get_redis()
        try:
            history = await self.get()
            message = ChatMessage(role=role, content=content)
            history.append(message.model_dump())

            # Keep max 50 messages per session
            await redis.setex(self.key, self.TTL, json.dumps(history[-50:]))
        finally:
            await redis.aclose()

    async def get(self) -> list[dict]:
        """Get session history"""
        redis = await self._get_redis()
        try:
            data = await redis.get(self.key)
            raw = json.loads(data) if data else []
            normalized = []
            for item in raw:
                try:
                    msg = ChatMessage.model_validate(item)
                    normalized.append(msg.model_dump())
                except Exception:
                    continue
            return normalized
        finally:
            await redis.aclose()

    async def clear(self):
        """Clear session history"""
        redis = await self._get_redis()
        try:
            await redis.delete(self.key)
        finally:
            await redis.aclose()

    async def get_messages(self) -> list[dict]:
        """Get messages in LLM format (role + content only)"""
        history = await self.get()
        return [{"role": msg["role"], "content": msg["content"]} for msg in history]

    async def get_approved_tasks(self) -> list[str]:
        """Get list of approved task IDs for this session"""
        redis = await self._get_redis()
        try:
            data = await redis.get(f"{self.key}:approved")
            return json.loads(data) if data else []
        finally:
            await redis.aclose()

    async def add_approved_task(self, task_id: str):
        """Add a task ID to the approved list"""
        redis = await self._get_redis()
        try:
            approved = await self.get_approved_tasks()
            if task_id not in approved:
                approved.append(task_id)
                await redis.setex(
                    f"{self.key}:approved", self.TTL, json.dumps(approved)
                )
        finally:
            await redis.aclose()


# Global instances
_long_term_memory: Optional[LongTermMemory] = None
_session_memories: dict[str, SessionMemory] = {}


def get_long_term_memory() -> LongTermMemory:
    """Get or create long-term memory instance"""
    global _long_term_memory
    if _long_term_memory is None:
        _long_term_memory = LongTermMemory()
    return _long_term_memory


def get_session_memory(session_id: str) -> SessionMemory:
    """Get or create session memory for user"""
    if session_id not in _session_memories:
        _session_memories[session_id] = SessionMemory(session_id)
    return _session_memories[session_id]
