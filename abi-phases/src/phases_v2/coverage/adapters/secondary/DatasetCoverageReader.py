"""The coverage report's reads, from this module's datasets and PubMed's.

Every query runs against one pinned snapshot. Snapshots are catalog-wide, so
the ``pubmed`` tables are read at the same instant as ``phases_v2``'s, and the
counts in one report always agree with each other. The counting is done in SQL:
only aggregates come back, never the extractions or items themselves.

Folders are listed in object storage, which has no snapshot; a folder document
that nothing has ingested is read once to learn its content hash, so it is
counted once however many paths hold it.

Nothing here writes. The class has no write method, and the store it is given
is pinned, which refuses writes. The relations check validates each outstanding
item with the projector's own ``relation_rows`` and keeps nothing.
"""

from __future__ import annotations

import logging
from hashlib import sha256
from typing import Any

from phases_v2.coverage.interfaces import (
    FAILED_CALL,
    GRAPH,
    INVALID_ANSWER,
    NOT_RUN,
    RELATIONS,
    SUCCEEDED,
    VECTOR_CHUNKS,
    VECTOR_ITEMS,
    Backlog,
    Collection,
    CoverageCount,
    FailureCount,
    PromptVersion,
    RelationCheck,
    SavedSearch,
    Selection,
)
from phases_v2.paper_collections.interfaces import Artifact, MemberSources
from phases_v2.ports import RowStore
from phases_v2.sources.library_links import PUBMED, linked_schemas
from phases_v2.sql import literal

logger = logging.getLogger(__name__)

# How a stored extraction reads: failed with no answer kept is a failed call.
_STATE = (
    f"CASE WHEN e.extraction_id IS NULL THEN {literal(NOT_RUN)} "
    f"WHEN e.status = {literal(SUCCEEDED)} THEN {literal(SUCCEEDED)} "
    f"WHEN coalesce(trim(e.raw_response), '') = '' THEN {literal(FAILED_CALL)} "
    f"ELSE {literal(INVALID_ANSWER)} END"
)


def _values(rows: list[tuple[str, ...]]) -> str:
    return ", ".join("(" + ", ".join(literal(v) for v in row) + ")" for row in rows)


def _selected(selection: Selection) -> str:
    """The selected models × prompt versions, as a table."""
    pairs = [(m, p) for m in selection.models for p in selection.prompt_ids]
    if not pairs:
        return "(SELECT NULL, NULL WHERE FALSE)"
    return f"(VALUES {_values(pairs)})"


def _chosen(selection: Selection) -> str:
    """Whether a row joined to ``selected sel`` and ``chunks c`` is in the selection."""
    return (
        f"sel.model_id IS NOT NULL AND c.chunker_id = {literal(selection.chunker_id)}"
    )


def _pending(target: str, key: str) -> str:
    return (
        "NOT EXISTS (SELECT 1 FROM projections done "
        f"WHERE done.target = {literal(target)} AND done.key = {key})"
    )


# Items of succeeded extractions, as the vector and relations projectors read them.
_SUCCEEDED_ITEMS = (
    "FROM extracted_items ei "
    "JOIN extractions e ON e.extraction_id = ei.extraction_id "
    "AND e.status = 'succeeded' "
    "LEFT JOIN chunks c ON c.chunk_id = e.chunk_id "
    "LEFT JOIN selected sel ON sel.model_id = e.model_id "
    "AND sel.prompt_id = e.prompt_id "
)
_RELATION_ITEMS = (
    f"{_SUCCEEDED_ITEMS}JOIN prompts p ON p.prompt_id = ei.prompt_id "
    "AND p.output_key = 'relations' "
)


class PinnedDataset:
    """The dataset service, reading only, at one snapshot.

    Hands :class:`~phases_v2.sources.adapters.secondary.phases_v2_pubmed_catalog.PubmedCatalog`
    the same snapshot as everything else. It offers no way to write.
    """

    def __init__(self, dataset: Any, snapshot: int | None):
        self._dataset = dataset
        self._snapshot = snapshot

    def describe(self, name: str, *, namespace: str = "default"):
        return self._dataset.describe(name, namespace=namespace)

    def query(self, sql: str, *, namespace: str = "default", snapshot_id=None):
        return self._dataset.query(sql, namespace=namespace, snapshot_id=self._snapshot)


class ContentAddressedSources:
    """Member sources that name every folder document by its content.

    A document something already ingested is known by its path; any other is
    read and hashed, which is the id it will have once ingested.
    """

    def __init__(self, inner: MemberSources, storage: Any):
        self._inner = inner
        self._storage = storage

    def folder(self, prefix):
        return self._inner.folder(prefix)

    def pubmed_query(self, query_id):
        return self._inner.pubmed_query(query_id)

    def pubmed_paper(self, pmid):
        return self._inner.pubmed_paper(pmid)

    def ingested_paper(self, paper_id):
        return self._inner.ingested_paper(paper_id)

    def paper_ids_by_path(self, paths):
        found = dict(self._inner.paper_ids_by_path(paths))
        for path in paths:
            if path in found:
                continue
            prefix, _, key = path.rpartition("/")
            try:
                content = self._storage.get_object(prefix, key)
            except Exception as failure:  # noqa: BLE001 - any storage error leaves it unknown
                logger.warning(
                    "Could not read %s to identify it; it is counted by path: %s",
                    path,
                    failure,
                    exc_info=True,
                )
                continue
            found[path] = sha256(content).hexdigest()
        return found


class DatasetCoverageReader:
    def __init__(
        self,
        rows: RowStore,
        *,
        snapshot: int | None,
        pubmed: Any,
        storage: Any,
        supported,
    ):
        """``rows`` is pinned to ``snapshot``; ``pubmed`` is a ``PubmedCatalog``
        over a :class:`PinnedDataset` at the same snapshot."""
        from phases_v2.paper_collections.adapters.secondary.StoredMemberSources import (
            StoredMemberSources,
        )

        self._rows = rows
        self._snapshot = snapshot
        self._pubmed = pubmed
        self._supported = supported
        self._sources = ContentAddressedSources(
            StoredMemberSources(rows, storage, pubmed), storage
        )
        self._schemas: set[str] | None = None

    def _has_pubmed(self) -> bool:
        if self._schemas is None:
            self._schemas = linked_schemas(self._rows)
        return PUBMED[0] in self._schemas

    # -- sources --------------------------------------------------------

    def snapshot(self):
        return self._snapshot

    def collections(self):
        from phases_v2.app.app_resources import AppResources

        return [
            Collection(c["collection_id"], c["name"], c["members"])
            for c in AppResources(self._rows, papers_root="").collections()
        ]

    def saved_searches(self):
        if not self._has_pubmed():
            return []
        return [
            SavedSearch(q["query_id"], q["query"])
            for q in self._pubmed.queries()["queries"]
            if int(q.get("published_paper_count") or 0) > 0
        ]

    def member_sources(self):
        return self._sources

    def supported(self, file_name):
        return self._supported(file_name)

    def downloaded_pdfs(self):
        if not self._has_pubmed():
            return []
        return [
            Artifact(
                r["storage_prefix"],
                r["storage_key"],
                content_sha256=r["content_sha256"] or None,
                artifact_id=r["artifact_id"],
                pmid=r["pmid"],
            )
            for r in self._rows.query(
                "SELECT artifact_id, pmid, storage_prefix, storage_key, content_sha256 "
                "FROM pubmed.artifacts WHERE status = 'ready' AND contract_version = 1 "
                "ORDER BY pmid, artifact_id"
            )
        ]

    def ingested_papers(self):
        return [
            Artifact(
                r["storage_prefix"], r["storage_key"], content_sha256=r["paper_id"]
            )
            for r in self._rows.query(
                "SELECT paper_id, storage_prefix, storage_key FROM papers "
                "WHERE text_key IS NOT NULL ORDER BY paper_id"
            )
        ]

    def chunked_papers(self, chunker_id):
        return {
            r["paper_id"]
            for r in self._rows.query(
                "SELECT DISTINCT paper_id FROM chunks "  # nosec B608 - values go through sql.literal
                f"WHERE chunker_id = {literal(chunker_id)}"
            )
        }

    # -- counts ---------------------------------------------------------

    def coverage(self, scopes, selection: Selection):
        members = [
            (scope, p) for scope, ids in scopes.items() for p in dict.fromkeys(ids)
        ]
        pairs = [(m, p) for m in selection.models for p in selection.prompt_ids]
        if not members or not pairs:
            return []
        rows = self._rows.query(
            f"WITH scope(scope, paper_id) AS (VALUES {_values(members)}), "  # nosec B608
            f"selected(model_id, prompt_id) AS (VALUES {_values(pairs)}), "
            "scoped AS (SELECT DISTINCT s.scope, c.chunk_id FROM scope s "
            "JOIN chunks c ON c.paper_id = s.paper_id "
            f"WHERE c.chunker_id = {literal(selection.chunker_id)}) "
            f"SELECT sc.scope, sel.model_id, sel.prompt_id, {_STATE} AS state, "
            "CASE WHEN e.status <> 'succeeded' THEN coalesce(e.error, '') END AS reason, "
            "count(*) AS chunks "
            "FROM scoped sc CROSS JOIN selected sel "
            "LEFT JOIN extractions e ON e.chunk_id = sc.chunk_id "
            "AND e.model_id = sel.model_id AND e.prompt_id = sel.prompt_id "
            "GROUP BY ALL"
        )
        return [
            CoverageCount(
                r["scope"],
                r["model_id"],
                r["prompt_id"],
                r["state"],
                r["reason"],
                int(r["chunks"]),
            )
            for r in rows
        ]

    def failures(self):
        return [
            FailureCount(
                r["prompt_id"], r["model_id"], r["state"], r["reason"], int(r["n"])
            )
            for r in self._rows.query(
                f"SELECT e.prompt_id, e.model_id, {_STATE} AS state, "  # nosec B608
                "coalesce(e.error, '') AS reason, count(*) AS n "
                "FROM extractions e WHERE e.status <> 'succeeded' GROUP BY ALL"
            )
        ]

    def prompt_versions(self):
        return [
            PromptVersion(
                r["prompt_id"], r["name"], int(r["extractions"]), int(r["succeeded"])
            )
            for r in self._rows.query(
                "SELECT coalesce(p.prompt_id, e.prompt_id) AS prompt_id, p.name, "
                "coalesce(e.n, 0) AS extractions, coalesce(e.ok, 0) AS succeeded "
                "FROM prompts p FULL OUTER JOIN (SELECT prompt_id, count(*) AS n, "
                "count(*) FILTER (WHERE status = 'succeeded') AS ok "
                "FROM extractions GROUP BY prompt_id) e ON e.prompt_id = p.prompt_id"
            )
        ]

    def run_requests(self):
        return self._rows.query(
            "SELECT * FROM run_requests ORDER BY requested_at DESC NULLS LAST, request_id"
        )

    def projection_backlog(self, selection: Selection):
        chosen = f"count(*) FILTER (WHERE {_chosen(selection)})"
        # Each target as its projector reads it: the graph takes succeeded
        # extractions, the vectors every chunk and the items of succeeded
        # extractions, the relations those items whose prompt answers with
        # relations. Every ledger key is the row id.
        rows = self._rows.query(
            f"WITH selected(model_id, prompt_id) AS {_selected(selection)} "  # nosec B608
            f"SELECT {literal(GRAPH)} AS target, count(*) AS outstanding, "
            f"{chosen} AS selected FROM extractions e "
            "LEFT JOIN chunks c ON c.chunk_id = e.chunk_id "
            "LEFT JOIN selected sel ON sel.model_id = e.model_id "
            "AND sel.prompt_id = e.prompt_id "
            f"WHERE e.status = 'succeeded' AND {_pending(GRAPH, 'e.extraction_id')} "
            f"UNION ALL SELECT {literal(VECTOR_CHUNKS)}, count(*), "
            "count(*) FILTER (WHERE c.chunker_id = "
            f"{literal(selection.chunker_id)}) FROM chunks c "
            f"WHERE {_pending(VECTOR_CHUNKS, 'c.chunk_id')} "
            f"UNION ALL SELECT {literal(VECTOR_ITEMS)}, count(*), {chosen} "
            f"{_SUCCEEDED_ITEMS}WHERE {_pending(VECTOR_ITEMS, 'ei.item_id')} "
            f"UNION ALL SELECT {literal(RELATIONS)}, count(*), {chosen} "
            f"{_RELATION_ITEMS}WHERE {_pending(RELATIONS, 'ei.item_id')}"
        )
        return [
            Backlog(r["target"], int(r["outstanding"]), int(r["selected"]))
            for r in rows
        ]

    def relation_check(self, selection: Selection):
        from phases_v2.projection.adapters.secondary.ProbabilisticContractValidator import (
            validate_relation,
        )
        from phases_v2.projection.probabilistic import REJECTED, relation_rows

        examined = rejected = rejected_selected = 0
        errors: dict[str, str] = {}
        for item in self._rows.query(
            f"WITH selected(model_id, prompt_id) AS {_selected(selection)} "  # nosec B608
            "SELECT ei.item_id, ei.extraction_id, ei.chunk_id, ei.paper_id, "
            "ei.prompt_id, ei.text, e.model_id, "
            f"coalesce({_chosen(selection)}, FALSE) AS chosen "
            f"{_RELATION_ITEMS}WHERE {_pending(RELATIONS, 'ei.item_id')} "
            "ORDER BY ei.item_id"
        ):
            examined += 1
            try:
                relation_rows(item, validate_relation)
            except REJECTED as error:
                rejected += 1
                rejected_selected += bool(item["chosen"])
                if len(errors) < 20:
                    errors[item["item_id"]] = str(error)
        return RelationCheck(examined, rejected, rejected_selected, errors)
