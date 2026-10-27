"""The PubMed library and OpenAlex records a phases_v2 paper links to.

- PubMed, by content hash: a published PDF's ``content_sha256`` is the
  phases_v2 paper's identity, so the two name the same file.
- OpenAlex enrichment, by the PubMed PMID.

Those tables belong to their own modules and share this store's catalog. They
are read by SQL, as their contracts allow, and only when they exist: a
deployment without those modules still lists and serves its papers. Read-only.
"""

from __future__ import annotations

from typing import Any

from phases_v2.ports import RowStore
from phases_v2.sql import in_list, literal

PUBMED = ("pubmed", ("artifacts", "papers"))
OPENALEX = ("openalex", ("paper_enrichments", "works"))

#: One row per published content hash: its PMID and PubMed title. Read-only.
_PUBMED_BY_HASH = """
SELECT a.content_sha256, a.pmid, pp.title
FROM (
    SELECT content_sha256, min(pmid) AS pmid FROM pubmed.artifacts
    WHERE status = 'ready' AND contract_version = 1 AND content_sha256 <> ''
    GROUP BY content_sha256
) a
LEFT JOIN (
    SELECT pmid, any_value(title) AS title FROM pubmed.papers GROUP BY pmid
) pp ON pp.pmid = a.pmid
"""

_NO_PUBMED = (
    "SELECT CAST(NULL AS VARCHAR) AS content_sha256, "
    "CAST(NULL AS VARCHAR) AS pmid, CAST(NULL AS VARCHAR) AS title WHERE FALSE"
)


def linked_schemas(rows: RowStore) -> set[str]:
    """The linked modules whose tables all exist in this store."""
    wanted = {schema: set(tables) for schema, tables in (PUBMED, OPENALEX)}
    found: dict[str, set[str]] = {}
    for row in rows.query(
        "SELECT table_schema, table_name FROM information_schema.tables "  # nosec B608
        "WHERE table_catalog = current_database() "
        f"AND table_schema IN {in_list(sorted(wanted))}"
    ):
        found.setdefault(row["table_schema"], set()).add(row["table_name"])
    return {
        schema
        for schema, tables in wanted.items()
        if tables <= found.get(schema, set())
    }


def pubmed_by_hash(schemas: set[str]) -> str:
    """SQL for ``(content_sha256, pmid, title)``, empty without PubMed."""
    return _PUBMED_BY_HASH if PUBMED[0] in schemas else _NO_PUBMED


def pubmed_pmid(rows: RowStore, schemas: set[str], sha256: str | None) -> str | None:
    """The PMID whose published PDF has this content, if PubMed has one."""
    if PUBMED[0] not in schemas or not sha256:
        return None
    found = rows.query(
        "SELECT min(pmid) AS pmid FROM pubmed.artifacts "  # nosec B608
        "WHERE status = 'ready' AND contract_version = 1 "
        f"AND content_sha256 = {literal(sha256)}"
    )
    return found[0]["pmid"] if found else None


def pubmed_record(rows: RowStore, schemas: set[str], pmid: str) -> dict | None:
    if PUBMED[0] not in schemas or not pmid:
        return None
    found = rows.query(
        "SELECT pmid, pmcid, doi, title, journal, publication_date, authors "  # nosec B608
        f"FROM pubmed.papers WHERE pmid = {literal(pmid)} LIMIT 1"
    )
    return _plain(found[0]) if found else None


def openalex_record(rows: RowStore, schemas: set[str], pmid: str) -> dict | None:
    """The enrichment and its matched work, the way ``/openalex/api/papers`` has them."""
    if OPENALEX[0] not in schemas or not pmid:
        return None
    links = rows.query(
        "SELECT * FROM openalex.paper_enrichments "  # nosec B608
        f"WHERE pmid = {literal(pmid)} LIMIT 1"
    )
    if not links:
        return None
    link = _plain(links[0])
    works = (
        rows.query(
            "SELECT * FROM openalex.works "  # nosec B608
            f"WHERE work_id = {literal(link['work_id'])} LIMIT 1"
        )
        if link.get("work_id")
        else []
    )
    return {"enrichment": link, "work": _plain(works[0]) if works else None}


def is_published_pdf(
    rows: RowStore, schemas: set[str], prefix: str, key: str, sha256: str | None
) -> bool:
    """Whether PubMed published exactly this object as a PDF with this content."""
    if PUBMED[0] not in schemas or not sha256:
        return False
    return bool(
        rows.query(
            "SELECT 1 AS found FROM pubmed.artifacts "  # nosec B608
            "WHERE status = 'ready' AND contract_version = 1 "
            f"AND storage_prefix = {literal(prefix)} "
            f"AND storage_key = {literal(key)} "
            f"AND content_sha256 = {literal(sha256)} LIMIT 1"
        )
    )


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _plain(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _iso(value) for key, value in row.items()}
