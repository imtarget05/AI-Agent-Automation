"""
RAG Service - Document ingestion and retrieval API
"""

from pathlib import Path
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from shared.config import get_settings
from services.rag_service.store import RagStore
from services.rag_service.ingest import ingest_path

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


@app.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_docs(request: RetrieveRequest):
    """Retrieve top-K relevant chunks"""
    try:
        store = RagStore()
        results = await store.query(
            query=request.query,
            top_k=request.top_k,
            namespace=request.namespace,
        )
        return RetrieveResponse(query=request.query, results=results)
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
