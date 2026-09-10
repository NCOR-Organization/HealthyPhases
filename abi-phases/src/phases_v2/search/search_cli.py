"""Quick CLI to exercise the reverse-search domain against the live stores.

Bypasses the web server — useful to confirm the dataset + vector store actually
contain searchable data, and to eyeball results. Ported from
``phases.app.search_cli``.

Run (from the ABI project root, so the engine/module is bootstrapped):

    uv run abi run script src/phases_v2/search/search_cli.py -- semantic "solitude reduces stress"
    uv run abi run script src/phases_v2/search/search_cli.py -- keyword "loneliness cortisol"
    uv run abi run script src/phases_v2/search/search_cli.py -- prompts
"""

from __future__ import annotations

import sys

from phases_v2 import ABIModule
from phases_v2.search.factory import search_service


def _print_hits(hits) -> None:
    if not hits:
        print("  (no matches)")
        return
    for i, h in enumerate(hits, 1):
        score = f" score={h.score:.4f}" if h.score is not None else ""
        where = f" chunk#{h.chunk_seq}" if h.chunk_seq is not None else ""
        print(f"\n{i}.{score} [{h.prompt_name or '?'}] {h.paper_name or '(unknown)'}{where}")
        print(f"   {h.extracted_text}")


def main(argv: list[str]) -> None:
    mode = argv[0] if argv else "semantic"
    query = argv[1] if len(argv) > 1 else ""

    service = search_service(ABIModule.get_instance().engine)

    if mode == "prompts":
        print("Prompts:", ", ".join(service.list_prompts()) or "(none)")
        return
    if mode == "keyword":
        print(f"Keyword search: {query!r}")
        _print_hits(service.keyword_search(query, limit=15))
        return

    print(f"Semantic search: {query!r}")
    _print_hits(service.semantic_search(query, k=10))


if __name__ == "__main__":
    main(sys.argv[1:])
