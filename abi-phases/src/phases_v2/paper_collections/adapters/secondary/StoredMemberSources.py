"""Collection members read from object storage, the datasets and PubMed.

Folders are listed in object storage; ingested papers, their results and
folder names come from this module's datasets; saved searches and PubMed
papers come from the PubMed catalog, read fresh on every call so a live member
sees what was published since.
"""

from __future__ import annotations

import logging
from typing import Any

from phases_v2.paper_collections.interfaces import (
    FOLDER,
    PAPER,
    PUBMED_QUERY,
    Artifact,
    MemberUnavailable,
)
from phases_v2.papers.interfaces import ObjectNotFound
from phases_v2.ports import RowStore
from phases_v2.sql import in_list, literal

logger = logging.getLogger(__name__)

_PATH = "rtrim(storage_prefix, '/') || '/' || ltrim(storage_key, '/')"
_PATH_BATCH = 1000
_PAPERS = (
    "SELECT paper_id, storage_prefix, storage_key, file_name FROM papers "
    "WHERE text_key IS NOT NULL"
)


def _pubmed_artifact(row: dict[str, Any]) -> Artifact:
    return Artifact(
        storage_prefix=row["storage_prefix"],
        storage_key=row["storage_key"],
        content_sha256=row["content_sha256"],
        name=row.get("title") or row["storage_key"].rsplit("/", 1)[-1],
        artifact_id=row.get("artifact_id"),
        pmid=row.get("pmid"),
    )


def _paper_artifact(row: dict[str, Any]) -> Artifact:
    return Artifact(
        storage_prefix=row["storage_prefix"],
        storage_key=row["storage_key"],
        content_sha256=row["paper_id"],
        name=row.get("file_name") or row["storage_key"].rsplit("/", 1)[-1],
    )


class StoredMemberSources:
    def __init__(self, rows: RowStore, storage=None, pubmed=None):
        """``storage`` is the engine's object storage; ``pubmed`` a ``PubmedCatalog``."""
        self._rows = rows
        self._storage = storage
        self._pubmed = pubmed

    # -- resolution -----------------------------------------------------

    def folder(self, prefix: str) -> list[Artifact]:
        from phases_v2.papers.adapters.secondary.ObjectStorageSource import (
            ObjectStorageSource,
        )

        if self._storage is None:
            raise MemberUnavailable("Object storage is unavailable in this deployment.")
        try:
            keys = ObjectStorageSource(self._storage).list_objects_recursive(prefix)
        except ObjectNotFound:
            # A folder nothing has been uploaded to yet holds no papers.
            return []
        except Exception as failure:  # noqa: BLE001 - any storage error makes the folder unreadable
            logger.warning("Could not list %s: %s", prefix, failure, exc_info=True)
            raise MemberUnavailable(f"Could not read {prefix}: {failure}") from failure
        return [
            Artifact(prefix, key, name=key.rsplit("/", 1)[-1])
            for key in sorted(set(keys))
            if key and not key.endswith("/")
        ]

    def pubmed_query(self, query_id: str) -> list[Artifact]:
        return [_pubmed_artifact(row) for row in self._catalog().artifacts(query_id)]

    def pubmed_paper(self, pmid: str) -> list[Artifact]:
        return [_pubmed_artifact(r) for r in self._catalog().paper_artifacts(pmid)]

    def ingested_paper(self, paper_id: str) -> Artifact | None:
        rows = self._rows.query(f"{_PAPERS} AND paper_id = {literal(paper_id)}")
        return _paper_artifact(rows[0]) if rows else None

    def paper_ids_by_path(self, paths: list[str]) -> dict[str, str]:
        """Every path a paper was read from is in ``paper_paths``; ``papers``
        holds the first one, which is all there was before that dataset."""
        found: dict[str, str] = {}
        wanted = sorted(set(paths))
        for start in range(0, len(wanted), _PATH_BATCH):
            batch = in_list(wanted[start : start + _PATH_BATCH])
            for row in self._rows.query(
                "SELECT path, paper_id FROM paper_paths "  # nosec B608 - paths go through sql.literal
                f"WHERE path IN {batch}"
            ):
                found[row["path"]] = row["paper_id"]
            for row in self._rows.query(
                f"SELECT {_PATH} AS path, paper_id FROM papers "  # nosec B608
                f"WHERE text_key IS NOT NULL AND {_PATH} IN {batch}"
            ):
                found.setdefault(row["path"], row["paper_id"])
        return found

    # -- what the collection pages show ---------------------------------

    def pubmed_query_exists(self, query_id: str) -> bool:
        return query_id in self._catalog().query_texts([query_id])

    def labels(self, members: list[dict[str, Any]]) -> dict[str, str]:
        def ids(kind, field):
            return [m[field] for m in members if m["kind"] == kind and m.get(field)]

        folders = {}
        if ids(FOLDER, "prefix"):
            folders = {
                row["prefix"]: row["name"]
                for row in self._rows.query(
                    "SELECT prefix, name FROM input_locations "
                    f"WHERE prefix IN {in_list(ids(FOLDER, 'prefix'))}"
                )
            }
        queries = (
            self._pubmed.query_texts(ids(PUBMED_QUERY, "query_id"))
            if self._pubmed
            else {}
        )
        titles = self._pubmed.titles(ids(PAPER, "pmid")) if self._pubmed else {}
        files = {}
        if ids(PAPER, "paper_id"):
            files = {
                row["paper_id"]: row["file_name"]
                for row in self._rows.query(
                    f"{_PAPERS} AND paper_id IN {in_list(ids(PAPER, 'paper_id'))}"
                )
            }
        labels = {}
        for m in members:
            if m["kind"] == FOLDER:
                label = folders.get(m["prefix"]) or m["prefix"]
            elif m["kind"] == PUBMED_QUERY:
                label = (
                    queries.get(m["query_id"]) or "PubMed search (no longer available)"
                )
            elif m.get("pmid"):
                label = titles.get(m["pmid"]) or f"PMID {m['pmid']}"
            else:
                label = files.get(m["paper_id"]) or "Paper (not in the library)"
            labels[m["member_id"]] = label
        return labels

    def paper_states(self, paper_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not paper_ids:
            return {}
        ids = in_list(sorted(set(paper_ids)))
        states = {
            row["paper_id"]: {"ingested": True, "results": 0}
            for row in self._rows.query(f"{_PAPERS} AND paper_id IN {ids}")
        }
        for row in self._rows.query(
            "SELECT paper_id, COUNT(*) AS results FROM extracted_items "  # nosec B608 - ids go through sql.literal
            f"WHERE paper_id IN {ids} GROUP BY paper_id"
        ):
            states.setdefault(row["paper_id"], {"ingested": True, "results": 0})
            states[row["paper_id"]]["results"] = int(row["results"])
        return states

    def _catalog(self):
        if self._pubmed is None:
            raise MemberUnavailable("PubMed papers are unavailable in this deployment.")
        return self._pubmed
