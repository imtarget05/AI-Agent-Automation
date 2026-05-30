"""
RAG Store - Qdrant-backed document storage and retrieval
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, Iterable

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

from shared.config import get_settings
from shared.llm import get_llm_router

logger = logging.getLogger(__name__)


class RagStore:
    """RAG vector store using Qdrant"""

    def __init__(self, collection: Optional[str] = None):
        self.settings = get_settings()
        self.collection = collection or self.settings.rag_collection
        self.client = AsyncQdrantClient(url=self.settings.qdrant_url)
        self.router = get_llm_router()
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_collection(self, vector_size: int):
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            try:
                info = await self.client.get_collection(self.collection)
                existing_size = info.config.params.vectors.size
                if existing_size != vector_size:
                    logger.warning(
                        "RAG collection vector size mismatch: %s vs %s",
                        existing_size,
                        vector_size,
                    )
            except Exception:
                await self.client.create_collection(
                    self.collection,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
            self._initialized = True

    async def upsert_chunks(self, chunks: Iterable[dict], namespace: str = "docs") -> int:
        """Upsert chunks into Qdrant; returns count"""
        chunks = list(chunks)
        if not chunks:
            return 0

        # Initialize collection using first embedding size
        sample_vector = await self.router.embed(chunks[0]["text"])
        await self._ensure_collection(len(sample_vector))

        points = []
        for chunk in chunks:
            vector = sample_vector if chunk is chunks[0] else await self.router.embed(chunk["text"])
            payload = {
                "text": chunk["text"],
                "source": chunk.get("source"),
                "chunk_index": chunk.get("chunk_index"),
                "namespace": namespace,
                "created_at": datetime.utcnow().isoformat(),
            }
            points.append(PointStruct(id=str(uuid.uuid4()), vector=vector, payload=payload))

        await self.client.upsert(self.collection, points=points)
        return len(points)

    async def query(self, query: str, top_k: int = 5, namespace: Optional[str] = None) -> list[dict]:
        """Search for relevant chunks"""
        query_vector = await self.router.embed(query)

        search_filter = None
        if namespace:
            search_filter = Filter(
                must=[FieldCondition(key="namespace", match=MatchValue(value=namespace))]
            )

        results = await self.client.search(
            self.collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter=search_filter,
        )

        return [
            {
                "id": r.id,
                "text": r.payload.get("text"),
                "source": r.payload.get("source"),
                "chunk_index": r.payload.get("chunk_index"),
                "score": r.score,
            }
            for r in results
        ]
