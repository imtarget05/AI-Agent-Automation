"""Seed curated cloned-repo documentation into vector memory."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.open_source_knowledge import seed_open_source_knowledge  # noqa: E402


async def main() -> None:
    """Run the same curated indexing path used by Gateway startup."""
    result = await seed_open_source_knowledge(force=True)
    print(
        "Seeded open-source knowledge: "
        f"{result.get('repos_indexed', 0)} repo docs, "
        f"{result.get('chunks_indexed', 0)} chunks"
    )


if __name__ == "__main__":
    asyncio.run(main())
