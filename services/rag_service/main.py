"""
RAG Service - Document ingestion and retrieval API
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from services.rag_service.graph_rag import GraphRagService
from services.rag_service.ingest import ingest_path
from services.rag_service.store import RagStore
from shared.config import get_settings
from shared.llm import get_llm_router

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="RAG Service",
    description="Document ingestion and retrieval",
    version="0.1.0",
)


class IngestRequest(BaseModel):
    path: str | None = None
    include_readme: bool = True
    extensions: list[str] | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    namespace: str = "docs"


class RetrieveRequest(BaseModel):
    query: str
    top_k: int = Field(default_factory=lambda: settings.rag_default_top_k)
    namespace: str | None = "docs"


class RetrieveResponse(BaseModel):
    query: str
    results: list[dict]


def _resolve_base_path(path: str | None) -> Path:
    base = Path(path or settings.rag_docs_path)
    if not base.is_absolute():
        base = Path("/app") / base
    return base


@app.post("/ingest")
async def ingest_docs(request: IngestRequest):
    """Ingest documents from docs/ and README.md"""
    base_path = _resolve_base_path(request.path)
    if not base_path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {base_path}")

    try:
        result = await ingest_path(
            base_path=base_path,
            include_readme=request.include_readme,
            extensions=request.extensions,
            chunk_size=request.chunk_size,
            overlap=request.chunk_overlap,
            namespace=request.namespace,
        )
        return {"status": "ok", **result}
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class RagManager:
    """Manages advanced RAG operations like Multi-query and Re-ranking"""

    def __init__(self):
        self.store = RagStore()
        self.llm = get_llm_router()

    async def retrieve_advanced(
        self, query: str, top_k: int = 5, namespace: str = "docs"
    ) -> List[dict]:
        """Multi-query retrieval with Semantic Re-ranking"""
        logger.info(f"[RAG] Advanced retrieval for: {query}")

        # 1. Query Expansion
        expansion_prompt = f"""You are a RAG assistant. Generate 3 concise alternative versions of the user query
to improve vector search retrieval.
User query: {query}
Return only the 3 queries separated by newlines. Do not add numbering or intro."""

        try:
            expansion_res = await self.llm.chat(
                [{"role": "user", "content": expansion_prompt}], task="planning"
            )
            queries = [q.strip() for q in expansion_res.split("\n") if q.strip()][:3]
            queries.append(query)  # Include original
            logger.info(f"[RAG] Expanded queries: {queries}")
        except Exception as e:
            logger.warning(f"Query expansion failed: {e}. Using original query only.")
            queries = [query]

        # 2. Parallel Vector Search
        all_results = []
        seen_ids = set()

        search_tasks = [
            self.store.query(q, top_k=top_k * 2, namespace=namespace) for q in queries
        ]
        search_results = await asyncio.gather(*search_tasks)

        for results in search_results:
            for r in results:
                if r["id"] not in seen_ids:
                    all_results.append(r)
                    seen_ids.add(r["id"])

        if not all_results:
            return []

        # 3. Semantic Re-ranking (LLM-based)
        if len(all_results) > top_k:
            logger.info(
                f"[RAG] Re-ranking {len(all_results)} candidates down to {top_k}"
            )
            context_list = "\n".join(
                [
                    f"[{i}] (Source: {r.get('source')}): {r['text'][:300]}..."
                    for i, r in enumerate(all_results)
                ]
            )

            rerank_prompt = f"""Given the User Query: "{query}"
Rank the following context snippets by relevance. Return only the indices of the top {top_k} most relevant snippets, separated by commas.
Context snippets:
{context_list}

Top {top_k} Indices:"""

            try:
                rerank_res = await self.llm.chat(
                    [{"role": "user", "content": rerank_prompt}], task="summarize"
                )
                # Parse indices like "0, 2, 5"
                indices = [int(idx.strip()) for idx in re.findall(r"\d+", rerank_res)]
                ranked_results = []
                for idx in indices:
                    if 0 <= idx < len(all_results):
                        ranked_results.append(all_results[idx])

                if ranked_results:
                    results = ranked_results[:top_k]
                else:
                    results = []
            except Exception as e:
                logger.warning(
                    f"Re-ranking failed: {e}. Falling back to score-based ranking."
                )
                results = []
        else:
            results = []

        if not results:
            all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            results = all_results[:top_k]

        # 4. Corrective RAG: Document Grading (if enabled)
        # Note: rag_verification_enabled and rag_grading_threshold should be in settings
        if getattr(settings, "rag_verification_enabled", False):
            logger.info(f"[RAG] Grading {len(results)} documents for accuracy.")
            graded_results = []

            async def grade_chunk(chunk):
                grade_prompt = f"""You are a Relevance Grader. Assess if the following document snippet is RELEVANT to the user query.
User Query: {query}
Snippet: {chunk["text"][:1000]}

Rate relevance from 0.0 to 1.0 (where 1.0 is highly relevant, 0.0 is completely irrelevant).
Return ONLY the numerical score."""
                try:
                    score_res = await self.llm.chat(
                        [{"role": "user", "content": grade_prompt}], task="summarize"
                    )
                    score = float(re.search(r"\d+\.?\d*", score_res).group())
                    return chunk, score
                except Exception as e:
                    logger.warning(f"Grading chunk failed: {e}")
                    return chunk, 0.5  # Neutral fallback

            grading_tasks = [grade_chunk(r) for r in results]
            graded_pairs = await asyncio.gather(*grading_tasks)

            for chunk, score in graded_pairs:
                if score >= getattr(settings, "rag_grading_threshold", 0.5):
                    chunk["relevance_score"] = score
                    graded_results.append(chunk)
                else:
                    logger.info(
                        f"[RAG] Filtering irrelevant chunk (score {score}) from {chunk.get('source')}"
                    )

            if not graded_results and results:
                logger.warning(
                    "[RAG] All chunks filtered out by grader! Using top chunk as fallback."
                )
                results[0]["relevance_score"] = 0.5
                return [results[0]]

            return graded_results

        return results


graph_rag_service = GraphRagService()


@app.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_docs(request: RetrieveRequest):
    """Retrieve top-K relevant chunks using advanced RAG manager and GraphRAG topology enrichment"""
    try:
        manager = RagManager()
        results = await manager.retrieve_advanced(
            query=request.query,
            top_k=request.top_k,
            namespace=request.namespace or "docs",
        )

        # Enrich the retrieved results with topological relationships (GraphRAG)
        enriched_results = graph_rag_service.enrich_retrieval_with_graph(
            query=request.query, vector_results=results
        )

        return RetrieveResponse(query=request.query, results=enriched_results)
    except Exception as e:
        logger.error(f"Retrieve failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "rag_service"}


@app.get("/")
async def root():
    return {
        "name": "RAG Service",
        "endpoints": {
            "ingest": "POST /ingest",
            "retrieve": "POST /retrieve",
            "health": "GET /health",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "services.rag_service.main:app",
        host="0.0.0.0",
        port=8007,
        reload=False,
    )
