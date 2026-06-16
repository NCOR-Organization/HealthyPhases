"""Quick CLI to exercise the reverse-search domain against the live stores.

Bypasses the web server — useful to confirm the KG + vector store actually
contain searchable data, and to eyeball results.

Run (from the ABI project root, so the engine/module is bootstrapped):

    uv run abi run script src/phases/app/search_cli.py -- semantic "solitude reduces stress"
    uv run abi run script src/phases/app/search_cli.py -- keyword "loneliness cortisol"
    uv run abi run script src/phases/app/search_cli.py -- pipelines
"""

from __future__ import annotations

import sys

from phases import ABIModule
from phases.app.factory import SearchServiceFactory


def _print_hits(hits) -> None:
    if not hits:
        print("  (no matches)")
        return
    for i, h in enumerate(hits, 1):
        score = f" score={h.score:.4f}" if h.score is not None else ""
        where = f" chunk#{h.chunk_number}" if h.chunk_number is not None else ""
        print(f"\n{i}.{score} [{h.pipeline or '?'}] {h.paper_name or '(unknown)'}{where}")
        print(f"   {h.extracted_text}")


def main(argv: list[str]) -> None:
    mode = argv[0] if argv else "semantic"
    query = argv[1] if len(argv) > 1 else ""

    service = SearchServiceFactory.from_engine(ABIModule.get_instance().engine)

    if mode == "pipelines":
        print("Pipelines:", ", ".join(service.list_pipelines()) or "(none)")
        return
    if mode == "keyword":
        print(f"Keyword search: {query!r}")
        _print_hits(service.keyword_search(query, limit=15))
        return

    print(f"Semantic search: {query!r}")
    _print_hits(service.semantic_search(query, k=10))


if __name__ == "__main__":
    main(sys.argv[1:])
