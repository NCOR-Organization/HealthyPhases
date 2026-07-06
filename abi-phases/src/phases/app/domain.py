"""SearchService — business logic for reverse search.

Orchestrates the semantic index and the knowledge-graph ports into ranked,
fully-located :class:`SearchHit` results. Knows nothing about Qdrant, SPARQL or
OpenAI.
"""

from __future__ import annotations

import re

from phases.app.interfaces import IKnowledgeGraphPort, ISemanticIndexPort
from phases.app.models import SearchHit

# Semantic search over-fetches before optional pipeline filtering so a tight
# facet doesn't starve the result set.
_SEMANTIC_OVERFETCH = 4
_MAX_K = 100


def tokenize(query: str) -> list[str]:
    """Split a keyword query into word tokens (kept lowercase, deduped)."""
    seen: set[str] = set()
    tokens: list[str] = []
    for raw in re.findall(r"\w+", query.lower()):
        if raw and raw not in seen:
            seen.add(raw)
            tokens.append(raw)
    return tokens


class SearchService:
    def __init__(
        self,
        semantic_index: ISemanticIndexPort,
        knowledge_graph: IKnowledgeGraphPort,
    ):
        self._index = semantic_index
        self._kg = knowledge_graph

    def semantic_search(
        self,
        query: str,
        k: int = 10,
        score_threshold: float | None = None,
        pipelines: list[str] | None = None,
    ) -> list[SearchHit]:
        query = (query or "").strip()
        if not query:
            return []
        k = max(1, min(k, _MAX_K))

        fetch = k * _SEMANTIC_OVERFETCH if pipelines else k
        matches = self._index.search(query, k=fetch, score_threshold=score_threshold)
        if not matches:
            return []

        locations = self._kg.resolve_locations([m.extracted_item_id for m in matches])
        wanted = {p for p in pipelines} if pipelines else None

        hits: list[SearchHit] = []
        for match in matches:
            location = locations.get(match.extracted_item_id)
            if wanted is not None and (location is None or location.pipeline not in wanted):
                continue
            hits.append(
                SearchHit.build(
                    extracted_item_id=match.extracted_item_id,
                    extracted_text=match.text,
                    location=location,
                    score=match.score,
                )
            )
            if len(hits) >= k:
                break
        return hits

    def keyword_search(
        self,
        query: str,
        limit: int = 25,
        pipelines: list[str] | None = None,
    ) -> list[SearchHit]:
        tokens = tokenize(query)
        if not tokens:
            return []
        limit = max(1, min(limit, _MAX_K))

        rows = self._kg.keyword_search(tokens, pipelines=pipelines, limit=limit)
        return [
            SearchHit.build(
                extracted_item_id=item_id,
                extracted_text=text,
                location=location,
                score=None,
            )
            for item_id, text, location in rows
        ]

    def list_pipelines(self) -> list[str]:
        return self._kg.list_pipelines()
