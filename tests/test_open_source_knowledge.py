from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared.open_source_knowledge import (
    _extract_sections,
    seed_open_source_knowledge,
)


def test_extract_sections():
    text = """# Title
## Intro
Some text.
## Section 1
Content 1
### Sub 1
Sub content 1
## Section 2
Content 2
## Section 3
Content 3
"""
    include = ["## Section 1", "## Section 3"]
    result = _extract_sections(text, include)

    assert "## Section 1" in result
    assert "Content 1" in result
    assert "### Sub 1" in result
    assert "Sub content 1" in result
    assert "## Section 3" in result
    assert "Content 3" in result
    assert "## Intro" not in result
    assert "## Section 2" not in result
    assert "Content 2" not in result


def test_seed_open_source_knowledge_filtering(tmp_path):
    repo_root = tmp_path
    (repo_root / "mcp_reference").mkdir()
    (repo_root / "mcp_reference" / "README.md").write_text(
        "## Introduction\nWelcome.\n## Server Implementations\nServer A\n### Category 1\nServer B\n## Frameworks\nFramework X\n## Conclusion\nBye.",
        encoding="utf-8",
    )

    memory = SimpleNamespace(init=AsyncMock(), save=AsyncMock())

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "shared.open_source_knowledge.get_long_term_memory",
            lambda: memory,
        )

        # Force seeding to ignore cache
        asyncio.run(seed_open_source_knowledge(base_path=repo_root, force=True))

        saved_texts = [call.args[0] for call in memory.save.await_args_list]
        full_saved = "\n\n".join(saved_texts)

        assert "## Server Implementations" in full_saved
        assert "Server A" in full_saved
        assert "### Category 1" in full_saved
        assert "Server B" in full_saved
        assert "## Frameworks" in full_saved
        assert "Framework X" in full_saved
        assert "## Introduction" not in full_saved
        assert "Welcome" not in full_saved
        assert "## Conclusion" not in full_saved
        assert "Bye" not in full_saved


def test_seed_open_source_knowledge_uses_deterministic_ids(tmp_path):
    repo_root = tmp_path
    (repo_root / "agentscope").mkdir()
    (repo_root / "agentscope" / "README.md").write_text(
        "AgentScope helps build multi-agent applications.\n",
        encoding="utf-8",
    )
    (repo_root / "intelligent-app-suite").mkdir()
    (repo_root / "intelligent-app-suite" / "README.md").write_text(
        "Awesome LLM Apps covers RAG and MCP templates.\n",
        encoding="utf-8",
    )

    memory = SimpleNamespace(init=AsyncMock(), save=AsyncMock())

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "shared.open_source_knowledge.get_long_term_memory",
            lambda: memory,
        )

        first = asyncio.run(seed_open_source_knowledge(base_path=repo_root))
        first_ids = [call.kwargs["point_id"] for call in memory.save.await_args_list]

        memory.save.reset_mock()

        second = asyncio.run(seed_open_source_knowledge(base_path=repo_root))
        second_ids = [call.kwargs["point_id"] for call in memory.save.await_args_list]

    assert first == {"repos_indexed": 2, "chunks_indexed": 2}
    assert second == {"repos_indexed": 0, "chunks_indexed": 0}
    assert first_ids
    assert second_ids == []
    assert all(len(point_id) == 40 for point_id in first_ids)
    assert (repo_root / "data" / "open_source_knowledge_index.json").exists()


def test_seed_open_source_knowledge_includes_harness_readmes(tmp_path):
    (tmp_path / "harness-revfactory").mkdir()
    (tmp_path / "harness-revfactory" / "README.md").write_text(
        "Harness agent-team architecture patterns.\n",
        encoding="utf-8",
    )
    (tmp_path / "harness-upstream").mkdir()
    (tmp_path / "harness-upstream" / "README.md").write_text(
        "Harness open-source DevOps platform.\n",
        encoding="utf-8",
    )
    (tmp_path / "claw-code").mkdir()
    (tmp_path / "claw-code" / "README.md").write_text(
        "Claw-code CLI agent harness.\n",
        encoding="utf-8",
    )

    memory = SimpleNamespace(init=AsyncMock(), save=AsyncMock())

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "shared.open_source_knowledge.get_long_term_memory",
            lambda: memory,
        )
        result = asyncio.run(seed_open_source_knowledge(base_path=tmp_path))

    repos = {call.kwargs["metadata"]["repo"] for call in memory.save.await_args_list}
    assert result == {"repos_indexed": 3, "chunks_indexed": 3}
    assert repos == {"harness-revfactory", "harness-upstream", "claw-code"}


def test_seed_open_source_knowledge_balances_chunk_budget_across_sections(tmp_path):
    repo_root = tmp_path
    (repo_root / "mcp_reference").mkdir()
    large_section = "\n".join(
        f"- Server {index}: {('detail ' * 600).strip()}"
        for index in range(6)
    )
    (repo_root / "mcp_reference" / "README.md").write_text(
        "\n".join(
            [
                "## Introduction",
                "Skip me.",
                "## Server Implementations",
                large_section,
                "## Frameworks",
                "- Framework Alpha: concise summary.",
                "## Conclusion",
                "Ignore me too.",
            ]
        ),
        encoding="utf-8",
    )

    memory = SimpleNamespace(init=AsyncMock(), save=AsyncMock())

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "shared.open_source_knowledge.get_long_term_memory",
            lambda: memory,
        )
        monkeypatch.setitem(
            __import__("shared.open_source_knowledge", fromlist=["OPEN_SOURCE_REPO_LIMITS"]).OPEN_SOURCE_REPO_LIMITS,
            "mcp_reference",
            {
                "max_chunks": 2,
                "include_headings": [
                    "## Server Implementations",
                    "## Frameworks",
                ],
            },
        )

        result = asyncio.run(seed_open_source_knowledge(base_path=repo_root, force=True))

    saved_texts = [call.args[0] for call in memory.save.await_args_list]
    assert result == {"repos_indexed": 1, "chunks_indexed": 2}
    assert any("## Server Implementations" in chunk for chunk in saved_texts)
    assert any("## Frameworks" in chunk for chunk in saved_texts)
