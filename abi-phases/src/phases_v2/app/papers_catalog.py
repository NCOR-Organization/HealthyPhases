"""Ingested papers and their chunks, for every picker in the app and Results.

Collections adds single papers from this listing; Prompts tries a prompt on a
few chunks of one of them; Results lists them with what each run found.

Read-only. Each paper is returned as a plain dict, so a view can add fields
without changing the ones the others read.
"""

from __future__ import annotations

from typing import Any

from phases_v2.app.app_resources import ResourceNotFound
from phases_v2.app.paper_links import path_sql, request_scope
from phases_v2.ports import RowStore
from phases_v2.sources.library_links import linked_schemas, pubmed_by_hash
from phases_v2.sql import in_list, literal

PREVIEW_CHARS = 160


#: How the listing can be ordered. Every order ends on the paper id, so pages
#: never overlap or skip a paper between two reads.
SORTS = {
    "title": "lower(l.title), l.paper_id",
    "newest": "l.discovered_at DESC NULLS LAST, l.paper_id",
    "oldest": "l.discovered_at ASC NULLS LAST, l.paper_id",
}


class PapersCatalog:
    def __init__(self, rows: RowStore | None):
        self._rows = rows

    def papers(
        self,
        *,
        q: str = "",
        chunker_id: str = "",
        papers: list[str] | None = None,
        request_id: str = "",
        prompts: list[str] | None = None,
        prompt_ids: list[str] | None = None,
        models: list[str] | None = None,
        has_results: bool | None = None,
        sort: str = "title",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Ingested papers, one page at a time, with what was extracted from each.

        - ``q`` matches the file name, the path, the PubMed title or the PMID.
        - ``chunker_id``: only papers already chunked with it, the ones a
          prompt can be tried on with that chunker.
        - ``papers`` limits the list to those ids (a collection's, say); an
          empty list matches nothing.
        - ``request_id``: only the papers that run request covered.
        - ``prompts`` (names), ``prompt_ids`` (versions) and ``models``: only
          papers those were run on. The counts on each row then cover those
          runs only.
        - ``has_results``: papers with at least one extracted item (True) or
          none (False), within the runs chosen above.

        Each paper is titled by its PubMed title when the PDF came from PubMed,
        else by its file name. A fixed number of queries serves any page size.
        """
        page = {"papers": [], "total": 0, "limit": limit, "offset": offset}
        if self._rows is None or (papers is not None and not papers):
            return page
        if sort not in SORTS:
            raise ValueError(f"Sort by one of: {', '.join(SORTS)}.")
        chosen = (prompts or [], prompt_ids or [], models or [])
        ran = _run_filter(*chosen, prompt_column="e.prompt_id")
        found = _run_filter(*chosen, prompt_column="ei.prompt_id")
        where = []
        if q.strip():
            # contains() rather than LIKE, so % and _ in a search mean themselves.
            term = f"lower({literal(q.strip())})"
            where.append(
                f"(contains(lower(l.file_name), {term}) OR contains(lower(l.path), "
                f"{term}) OR contains(lower(coalesce(l.pubmed_title, '')), {term}) "
                f"OR l.pmid = {literal(q.strip())})"
            )
        if chunker_id:
            where.append(
                "EXISTS (SELECT 1 FROM chunks c WHERE c.paper_id = l.paper_id "
                f"AND c.chunker_id = {literal(chunker_id)})"
            )
        if papers is not None:
            where.append(f"l.paper_id IN {in_list(sorted(set(papers)))}")
        if request_id:
            scope = request_scope(self._rows, request_id)
            if scope is None:
                raise ResourceNotFound("That run request does not exist.")
            where.append(scope.sql("l"))
        if ran:
            where.append(
                "EXISTS (SELECT 1 FROM extractions e JOIN chunks c ON c.chunk_id = "
                f"e.chunk_id {_PROMPT_JOIN} WHERE c.paper_id = l.paper_id AND {ran})"
            )
        if has_results is not None:
            exists = (
                f"EXISTS (SELECT 1 {_items_from(models)} "
                f"WHERE ei.paper_id = l.paper_id{' AND ' + found if found else ''})"
            )
            where.append(exists if has_results else f"NOT {exists}")
        listed = _listed(linked_schemas(self._rows))
        scope_sql = " AND ".join(where) or "TRUE"
        rows = self._rows.query(
            f"{listed} SELECT l.*, count(*) OVER () AS total FROM listed l "  # nosec B608
            f"WHERE {scope_sql} ORDER BY {SORTS[sort]} "
            f"LIMIT {int(limit)} OFFSET {int(offset)}"
        )
        if rows:
            page["total"] = int(rows[0]["total"])
        elif offset:
            # Past the end: the window had no row to report the total on.
            total = self._rows.query(
                f"{listed} SELECT count(*) AS total FROM listed l WHERE {scope_sql}"  # nosec B608
            )
            page["total"] = int(total[0]["total"]) if total else 0
        counts = self._counts([row["paper_id"] for row in rows], ran, found, models)
        page["papers"] = [
            {
                "paper_id": row["paper_id"],
                "file_name": row["file_name"],
                "storage_prefix": row["storage_prefix"],
                "storage_key": row["storage_key"],
                "path": paper_path(row["storage_prefix"], row["storage_key"]),
                "discovered_at": _iso(row["discovered_at"]),
                "chunks": counts["chunks"].get(row["paper_id"], {}),
                "title": row["title"],
                "pmid": row["pmid"],
                "source": "pubmed" if row["pmid"] else "file",
                "extractions": {
                    status: counts[status].get(row["paper_id"], {}).get(status, 0)
                    for status in ("succeeded", "failed")
                },
                "items": counts["items"].get(row["paper_id"], {}),
                "item_count": sum(counts["items"].get(row["paper_id"], {}).values()),
            }
            for row in rows
        ]
        return page

    def _counts(
        self, paper_ids: list[str], ran: str, found: str, models: list[str] | None
    ) -> dict[str, dict[str, dict[str, int]]]:
        """Chunks per chunker, extractions per status and items per prompt name,
        for each paper, in one query."""
        counts: dict[str, dict[str, dict[str, int]]] = {
            kind: {} for kind in ("chunks", "succeeded", "failed", "items")
        }
        if not paper_ids or self._rows is None:
            return counts
        ids = in_list(paper_ids)
        for row in self._rows.query(
            "SELECT 'chunks' AS kind, paper_id, chunker_id AS key, count(*) AS n "  # nosec B608
            f"FROM chunks WHERE paper_id IN {ids} GROUP BY ALL UNION ALL "
            "SELECT e.status AS kind, c.paper_id, e.status AS key, count(*) AS n "
            f"FROM extractions e JOIN chunks c ON c.chunk_id = e.chunk_id {_PROMPT_JOIN} "
            f"WHERE c.paper_id IN {ids} AND e.status IN ('succeeded', 'failed')"
            f"{' AND ' + ran if ran else ''} GROUP BY ALL UNION ALL "
            "SELECT 'items' AS kind, ei.paper_id, coalesce(pr.name, ei.prompt_id) AS key, "
            f"count(*) AS n {_items_from(models)} WHERE ei.paper_id IN {ids}"
            f"{' AND ' + found if found else ''} GROUP BY ALL ORDER BY kind, paper_id, key"
        ):
            counts[row["kind"]].setdefault(row["paper_id"], {})[row["key"]] = int(
                row["n"]
            )
        return counts

    def chunks(self, paper_id: str, chunker_id: str) -> dict[str, Any]:
        """The paper's chunks with one chunker, each with a short preview."""
        if self._rows is None or not self._rows.query(
            "SELECT paper_id FROM papers "  # nosec B608
            f"WHERE paper_id = {literal(paper_id)} AND text_key IS NOT NULL LIMIT 1"
        ):
            raise ResourceNotFound("That paper has not been ingested.")
        rows = self._rows.query(
            "SELECT seq, chunk_id, length(text) AS chars, "  # nosec B608
            f"substr(text, 1, {PREVIEW_CHARS * 2}) AS head, token_count FROM chunks "
            f"WHERE paper_id = {literal(paper_id)} "
            f"AND chunker_id = {literal(chunker_id)} ORDER BY seq"
        )
        return {
            "paper_id": paper_id,
            "chunker_id": chunker_id,
            "chunks": [
                {
                    "seq": int(row["seq"]),
                    "chunk_id": row["chunk_id"],
                    "preview": _preview(row["head"] or "", row["chars"] or 0),
                    "token_count": row["token_count"],
                }
                for row in rows
            ],
            "chunked_with": sorted(self._chunk_counts([paper_id]).get(paper_id, {})),
        }

    def _chunk_counts(self, paper_ids: list[str]) -> dict[str, dict[str, int]]:
        if not paper_ids or self._rows is None:
            return {}
        counts: dict[str, dict[str, int]] = {}
        for row in self._rows.query(
            "SELECT paper_id, chunker_id, count(*) AS chunks FROM chunks "  # nosec B608
            f"WHERE paper_id IN {in_list(paper_ids)} GROUP BY paper_id, chunker_id"
        ):
            counts.setdefault(row["paper_id"], {})[row["chunker_id"]] = int(
                row["chunks"]
            )
        return counts


#: Every query that filters on a prompt's name reads it through this join.
_PROMPT_JOIN = "LEFT JOIN prompts pr ON pr.prompt_id = e.prompt_id"


def _items_from(models: list[str] | None) -> str:
    """Extracted items with their prompt; their model needs the extraction too."""
    joined = (
        "JOIN extractions e ON e.extraction_id = ei.extraction_id " if models else ""
    )
    return (
        f"FROM extracted_items ei {joined}"
        "LEFT JOIN prompts pr ON pr.prompt_id = ei.prompt_id"
    )


def _run_filter(
    prompts: list[str],
    prompt_ids: list[str],
    models: list[str],
    *,
    prompt_column: str,
) -> str:
    """The results chosen by prompt name, version and model.

    Reads ``pr.name``, ``prompt_column`` and ``e.model_id``.
    """
    tests = []
    if prompts:
        tests.append(f"pr.name IN {in_list(prompts)}")
    if prompt_ids:
        tests.append(f"{prompt_column} IN {in_list(prompt_ids)}")
    if models:
        tests.append(f"e.model_id IN {in_list(models)}")
    return " AND ".join(tests)


def _listed(schemas: set[str]) -> str:
    """The ``listed`` CTE: ingested papers with their PubMed title and path."""
    return (
        f"WITH pubmed_pdfs AS ({pubmed_by_hash(schemas)}), listed AS ("  # nosec B608
        "SELECT p.paper_id, p.file_name, p.storage_prefix, p.storage_key, "
        f"p.content_sha256, p.discovered_at, {path_sql('p')} AS path, "
        "pm.pmid, pm.title AS pubmed_title, "
        "coalesce(nullif(trim(pm.title), ''), p.file_name, p.paper_id) AS title "
        "FROM papers p LEFT JOIN pubmed_pdfs pm ON pm.content_sha256 = p.content_sha256 "
        "WHERE p.text_key IS NOT NULL)"
    )


def paper_path(prefix: str | None, key: str | None) -> str | None:
    if not key:
        return None
    return f"{(prefix or '').rstrip('/')}/{key}" if prefix else key


def _preview(head: str, chars: int) -> str:
    text = " ".join(head.split())
    if len(text) <= PREVIEW_CHARS and chars <= len(head):
        return text
    return text[:PREVIEW_CHARS].rstrip() + "…"


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
