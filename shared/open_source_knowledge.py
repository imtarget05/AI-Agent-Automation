"""Seed local open-source repo knowledge into long-term memory.

This keeps a small, curated set of cloned reference projects searchable by the
orchestrator without wiring their source code directly into the runtime path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from shared.memory import get_long_term_memory

OPEN_SOURCE_NAMESPACE = "open_source"
CACHE_FILENAME = "open_source_knowledge_index.json"

OPEN_SOURCE_REPOS: dict[str, tuple[str, ...]] = {
    "agentscope": (
        "README.md",
        "docs/changelog.md",
    ),
    "intelligent-app-suite": (
        "README.md",
        "QUICK_START.md",
        "WORKFLOW.md",
    ),
    "mcp_reference": (
        "README.md",
    ),
    "500-AI-Agents-Projects": (
        "README.md",
    ),
    "harness-revfactory": (
        "README.md",
    ),
    "harness-upstream": (
        "README.md",
    ),
    "claw-code": (
        "README.md",
    ),
}

OPEN_SOURCE_REPO_LIMITS: dict[str, dict[str, Any]] = {
    "mcp_reference": {
        "max_chunks": 20,
        "include_headings": [
            "## Server Implementations",
            "## Frameworks",
        ],
    },
    "harness-revfactory": {"max_chunks": 4},
    "harness-upstream": {"max_chunks": 2},
    "claw-code": {"max_chunks": 4},
}


def _extract_sections(text: str, include_headings: list[str]) -> str:
    """Extract sections of markdown text that start with specific headings and their subheadings."""
    if not include_headings:
        return text

    lines = text.split("\n")
    result = []
    collecting = False
    current_level = 99

    for line in lines:
        if line.startswith("#"):
            stripped = line.strip()
            # Find heading level
            level = 0
            for char in stripped:
                if char == "#":
                    level += 1
                else:
                    break

            # Check if this heading or its prefix matches an included heading
            is_included = any(
                stripped == h or stripped.startswith(h + " ") for h in include_headings
            )

            if is_included:
                collecting = True
                current_level = level
                result.append(line)
            elif level <= current_level:
                # Encountered a heading at the same or higher level that isn't included
                collecting = False
                current_level = 99
            elif collecting:
                # It's a subheading of an included heading
                result.append(line)
        elif collecting:
            result.append(line)

    return "\n".join(result).strip()


def _extract_named_sections(text: str, include_headings: list[str]) -> list[str]:
    """Extract each configured markdown section as a standalone text block."""
    if not include_headings:
        cleaned = text.strip()
        return [cleaned] if cleaned else []

    lines = text.split("\n")
    sections: list[str] = []
    current_lines: list[str] = []
    collecting = False
    current_level = 99

    for line in lines:
        if line.startswith("#"):
            stripped = line.strip()
            level = 0
            for char in stripped:
                if char == "#":
                    level += 1
                else:
                    break

            is_included = any(
                stripped == heading or stripped.startswith(heading + " ")
                for heading in include_headings
            )

            if is_included:
                if current_lines:
                    section = "\n".join(current_lines).strip()
                    if section:
                        sections.append(section)
                current_lines = [line]
                collecting = True
                current_level = level
                continue

            if collecting and level <= current_level:
                section = "\n".join(current_lines).strip()
                if section:
                    sections.append(section)
                current_lines = []
                collecting = False
                current_level = 99
                continue

        if collecting:
            current_lines.append(line)

    if current_lines:
        section = "\n".join(current_lines).strip()
        if section:
            sections.append(section)

    return sections


def _chunk_text(
    text: str,
    max_chars: int = 4000,
    max_chunks: int | None = None,
) -> Iterable[str]:
    """Split a document into bounded chunks for vector storage."""
    cleaned = text.strip()
    if not cleaned:
        return []

    paragraphs = cleaned.split("\n\n")
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""
            if max_chunks is not None and len(chunks) >= max_chunks:
                return chunks

        if len(paragraph) <= max_chars:
            current = paragraph
            continue

        for index in range(0, len(paragraph), max_chars):
            chunks.append(paragraph[index : index + max_chars])
            if max_chunks is not None and len(chunks) >= max_chunks:
                return chunks

    if current:
        chunks.append(current)
    if max_chunks is not None:
        return chunks[:max_chunks]

    return chunks


def _chunk_sections(
    sections: Iterable[str],
    max_chars: int = 4000,
    max_chunks: int | None = None,
) -> list[str]:
    """Chunk sections independently so capped budgets still cover each configured section."""
    section_chunks = [
        list(_chunk_text(section, max_chars=max_chars))
        for section in sections
        if section.strip()
    ]
    section_chunks = [chunks for chunks in section_chunks if chunks]
    if not section_chunks:
        return []

    if max_chunks is None:
        return [chunk for chunks in section_chunks for chunk in chunks]
    if max_chunks <= 0:
        return []

    if sum(len(chunks) for chunks in section_chunks) <= max_chunks:
        return [chunk for chunks in section_chunks for chunk in chunks]

    allocated: list[list[str]] = [[] for _ in section_chunks]

    for index, chunks in enumerate(section_chunks):
        if len([item for item in allocated if item]) >= max_chunks:
            break
        allocated[index].append(chunks[0])

    remaining = max_chunks - sum(len(chunks) for chunks in allocated)
    offset = 1
    while remaining > 0:
        made_progress = False
        for index, chunks in enumerate(section_chunks):
            if offset >= len(chunks):
                continue
            allocated[index].append(chunks[offset])
            remaining -= 1
            made_progress = True
            if remaining == 0:
                break
        if not made_progress:
            break
        offset += 1

    return [chunk for chunks in allocated for chunk in chunks]


def _point_id(source_path: Path, chunk_index: int, chunk_text: str) -> str:
    digest = hashlib.sha1(
        f"{source_path.as_posix()}::{chunk_index}::{chunk_text}".encode("utf-8")
    ).hexdigest()
    return digest


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_cache(cache_path: Path) -> dict:
    if not cache_path.exists():
        return {"files": {}}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("files"), dict):
            return data
    except Exception:
        pass
    return {"files": {}}


def _save_cache(cache_path: Path, cache: dict) -> None:
    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=True), encoding="utf-8")


def _repo_limits(repo_name: str) -> dict[str, Any]:
    return OPEN_SOURCE_REPO_LIMITS.get(repo_name, {})


async def seed_open_source_knowledge(
    base_path: Path | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Index curated local repo docs into long-term memory.

    The helper is idempotent per file chunk because it uses deterministic point IDs.
    """

    root = base_path or Path(__file__).resolve().parents[1]
    memory = get_long_term_memory()
    await memory.init()

    cache_path = root / "data" / CACHE_FILENAME
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = _load_cache(cache_path)
    cache_files = cache.setdefault("files", {})
    cache_dirty = False

    repos_indexed = 0
    chunks_indexed = 0

    for repo_name, relative_files in OPEN_SOURCE_REPOS.items():
        repo_root = root / repo_name
        if not repo_root.exists():
            continue

        for relative_file in relative_files:
            source_path = repo_root / relative_file
            if not source_path.exists() or not source_path.is_file():
                continue

            text = source_path.read_text(encoding="utf-8", errors="ignore")
            limits = _repo_limits(repo_name)
            sections = [text]

            # Apply heading filtering if configured
            include_headings = limits.get("include_headings")
            if include_headings:
                sections = _extract_named_sections(text, include_headings)
                text = "\n\n".join(sections)

            if not text.strip():
                continue

            content_hash = _hash_text(text)
            max_chunks = limits.get("max_chunks")
            cache_key = source_path.as_posix()
            cache_signature = f"{content_hash}:{max_chunks or 'all'}"
            cache_entry = cache_files.get(cache_key)
            if not force and cache_entry and cache_entry.get("signature") == cache_signature:
                continue

            chunks = _chunk_sections(sections, max_chunks=max_chunks)
            if not chunks:
                continue

            repos_indexed += 1
            for chunk_index, chunk_text in enumerate(chunks):
                await memory.save(
                    chunk_text,
                    namespace=OPEN_SOURCE_NAMESPACE,
                    point_id=_point_id(source_path, chunk_index, chunk_text),
                    metadata={
                        "repo": repo_name,
                        "source_path": source_path.as_posix(),
                        "chunk_index": chunk_index,
                    },
                )
                chunks_indexed += 1
            cache_files[cache_key] = {
                "signature": cache_signature,
                "hash": content_hash,
                "max_chunks": max_chunks,
                "chunks": len(chunks),
            }
            cache_dirty = True

    if cache_dirty:
        _save_cache(cache_path, cache)

    return {
        "repos_indexed": repos_indexed,
        "chunks_indexed": chunks_indexed,
    }
