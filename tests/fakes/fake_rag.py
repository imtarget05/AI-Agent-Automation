"""
tests/fakes/fake_rag.py — Fake RAG service for testing
=======================================================
Provides canned retrieval results without Qdrant or embedding calls.
"""

from __future__ import annotations

from typing import Any, Optional


class FakeRAGStore:
    """Configurable fake for RAG retrieval.

    Usage::

        store = FakeRAGStore(results=[{"text": "Restart pod to fix OOM"}])
        results = await store.search("high cpu alert")
    """

    def __init__(
        self,
        results: Optional[list[dict[str, Any]]] = None,
        score: float = 0.85,
    ) -> None:
        self._results = results or [
            {
                "text": "Runbook: for high CPU alerts, check for GC loops and memory leaks.",
                "metadata": {"source": "runbook/cpu.md", "section": "Troubleshooting"},
                "score": score,
            }
        ]
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    async def search(
        self,
        query: str,  # noqa: ARG002
        limit: int = 5,
        namespace: Optional[str] = None,  # noqa: ARG002
        score_threshold: float = 0.5,  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        self._call_count += 1
        return self._results[:limit]

    async def save(
        self,
        text: str,
        metadata: Optional[dict] = None,
        namespace: str = "general",
        point_id: Optional[str] = None,
    ) -> str:
        return point_id or "fake-point-id"

    def reset(self) -> None:
        self._call_count = 0


class FakeRAGClient:
    """HTTP client fake for the RAG service."""

    def __init__(
        self,
        results: Optional[list[dict[str, Any]]] = None,
        score: float = 0.85,
    ) -> None:
        self._store = FakeRAGStore(results=results, score=score)

    async def search(
        self,
        query: str,
        collection: Optional[str] = None,  # noqa: ARG002
        top_k: int = 5,
    ) -> dict[str, Any]:
        results = await self._store.search(query, limit=top_k)
        return {"results": results, "query": query}
