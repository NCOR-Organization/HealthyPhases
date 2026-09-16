"""Native filtered Qdrant pagination; old payloads use the legacy path until refreshed."""

from qdrant_client import models as qm

from phases_v2.projection.metadata import METADATA_VERSION
from phases_v2.search.models import SemanticMatch
from phases_v2.search.result_cache import SearchResultCache


class QdrantSemanticAdapter:
    def __init__(self, client, embedder):
        self._client = client
        self._embedder = embedder
        self._cache = SearchResultCache()
        self._readiness = SearchResultCache(ttl=30, max_entries=1)
        self._collection = "phases_v2_extracted_items"

    def ready(self):
        def check():
            if not self._client.collection_exists(self._collection):
                return False
            outdated = qm.Filter(
                must_not=[
                    qm.FieldCondition(
                        key="search_metadata_version",
                        match=qm.MatchValue(value=METADATA_VERSION),
                    )
                ]
            )
            return (
                self._client.count(
                    self._collection, count_filter=outdated, exact=True
                ).count
                == 0
            )

        return self._readiness.get_or_compute("ready", check)

    @staticmethod
    def _filters(prompts, models, paths):
        conditions = []
        for key, values in [
            ("prompt_name", prompts),
            ("model_id", models),
            ("source_ancestors", [p.strip("/") for p in paths or []]),
        ]:
            if values:
                conditions.append(
                    qm.FieldCondition(
                        key=key, match=qm.MatchAny(any=sorted(set(values)))
                    )
                )
        return qm.Filter(must=conditions) if conditions else None

    @staticmethod
    def _match(point, score):
        payload = point.payload or {}
        return SemanticMatch(
            payload["item_id"],
            (payload.get("payload") or {}).get("text", ""),
            float(score),
        )

    def page(
        self,
        query,
        limit,
        offset,
        score_threshold=None,
        prompts=None,
        models=None,
        paths=None,
        snapshot=None,
    ):
        if not query.strip():
            return [], 0
        filters = self._filters(prompts, models, paths)
        key = (
            snapshot,
            query.strip(),
            score_threshold,
            filters.model_dump_json() if filters else "",
        )
        vector = self._cache.get_or_compute(
            ("embedding", query.strip()),
            lambda: tuple(self._embedder.embed([query.strip()])[0]),
        )
        common = {
            "collection_name": self._collection,
            "query": list(vector),
            "query_filter": filters,
            "search_params": qm.SearchParams(exact=True),
            "with_vectors": False,
        }
        if score_threshold is None:
            total = self._cache.get_or_compute(
                ("count", snapshot, key[-1]),
                lambda: (
                    self._client.count(
                        self._collection, count_filter=filters, exact=True
                    ).count
                ),
            )
            if offset >= total:
                return [], total
            points = self._client.query_points(
                **common,
                limit=limit,
                offset=offset,
                with_payload=["item_id", "payload.text"],
            ).points
            return [self._match(point, point.score) for point in points], total

        # Metadata counts do not count vector similarity thresholds. Enumerate
        # just IDs/scores once, with filters and threshold evaluated in Qdrant.
        def ranked_ids():
            ranked, position = [], 0
            while True:
                points = self._client.query_points(
                    **common,
                    limit=1024,
                    offset=position,
                    score_threshold=score_threshold,
                    with_payload=False,
                ).points
                ranked.extend((point.id, point.score) for point in points)
                if len(points) < 1024:
                    return tuple(ranked)
                position += len(points)

        ranked = self._cache.get_or_compute(("threshold", key), ranked_ids)
        selected = ranked[offset : offset + limit]
        if not selected:
            return [], len(ranked)
        records = self._client.retrieve(
            self._collection,
            ids=[i for i, _ in selected],
            with_payload=["item_id", "payload.text"],
            with_vectors=False,
        )
        by_id = {point.id: point for point in records}
        return [self._match(by_id[i], score) for i, score in selected], len(ranked)
