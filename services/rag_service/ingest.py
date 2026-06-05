"""
RAG Ingestion Pipeline

Reads docs, chunks text, and stores embeddings in Qdrant.
"""

from pathlib import Path
import logging
from typing import Iterable, Optional

from pypdf import PdfReader

from shared.config import get_settings
from services.rag_service.store import RagStore

logger = logging.getLogger(__name__)
settings = get_settings()

DEFAULT_EXTENSIONS = [".md", ".pdf", ".tex", ".txt"]
MAX_INGEST_FILES = 200
MAX_INGEST_FILE_BYTES = 5 * 1024 * 1024
MAX_INGEST_CHUNKS = 1000


def _strip_markdown_front_matter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_pdf_file(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def read_file_text(path: Path) -> str:
    """Read file content based on extension"""
    suffix = path.suffix.lower()
    if suffix in [".md", ".tex", ".txt"]:
        text = _read_text_file(path)
        if suffix == ".md":
            text = _strip_markdown_front_matter(text)
        return text
    if suffix == ".pdf":
        return _read_pdf_file(path)
    return ""


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Simple text chunking with overlap"""
    if chunk_size <= 0:
        return [text]
    if overlap < 0:
        raise ValueError("overlap must be greater than or equal to 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_len:
            break
        start = end - overlap

    return chunks


def iter_files(
    base_path: Path, extensions: Optional[list[str]] = None
) -> Iterable[Path]:
    """Yield files under base path with matching extensions"""
    exts = extensions or DEFAULT_EXTENSIONS
    for path in base_path.rglob("*"):
        if path.is_file() and path.suffix.lower() in exts:
            yield path


def build_chunks(
    files: Iterable[Path],
    chunk_size: int,
    overlap: int,
) -> list[dict]:
    """Build chunk records from files"""
    chunks = []
    for file_path in files:
        if file_path.stat().st_size > MAX_INGEST_FILE_BYTES:
            logger.warning("Skipping oversized RAG source: %s", file_path)
            continue
        text = read_file_text(file_path)
        if not text.strip():
            continue
        for idx, chunk in enumerate(chunk_text(text, chunk_size, overlap)):
            chunks.append(
                {
                    "text": chunk,
                    "source": str(file_path),
                    "chunk_index": idx,
                }
            )
    return chunks


async def ingest_path(
    base_path: Path,
    include_readme: bool = True,
    extensions: Optional[list[str]] = None,
    chunk_size: Optional[int] = None,
    overlap: Optional[int] = None,
    namespace: str = "docs",
) -> dict:
    """Ingest files into Qdrant and return stats"""
    chunk_size = settings.rag_chunk_size if chunk_size is None else chunk_size
    overlap = settings.rag_chunk_overlap if overlap is None else overlap

    files = list(iter_files(base_path, extensions))[:MAX_INGEST_FILES]

    if include_readme:
        readme = base_path.parent / "README.md"
        if readme.exists():
            files.append(readme)

    chunks = build_chunks(files, chunk_size, overlap)[:MAX_INGEST_CHUNKS]
    if not chunks:
        return {"files": 0, "chunks": 0}

    store = RagStore()
    count = await store.upsert_chunks(chunks, namespace=namespace)

    return {
        "files": len(files),
        "chunks": count,
        "namespace": namespace,
    }
