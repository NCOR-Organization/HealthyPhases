"""Ingested papers and their chunks, for choosing what to try a prompt on.

Read-only. Each paper is returned as a plain dict so later views (per-paper
results, say) can add fields without changing the ones already here.
"""

from __future__ import annotations

from typing import Any

from phases_v2.app.app_resources import ResourceNotFound
from phases_v2.ports import RowStore
from phases_v2.sql import in_list, literal

PREVIEW_CHARS = 160


class PapersCatalog:
    def __init__(self, rows: RowStore | None):
        self._rows = rows

    def papers(
        self,
        *,
        q: str = "",
        chunker_id: str = "",
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Ingested papers whose file name contains ``q``, by file name.

        With ``chunker_id``, only papers already chunked with it: those are the
        ones a prompt can be tried on with that chunker.
        """
        page = {"papers": [], "total": 0, "limit": limit, "offset": offset}
        if self._rows is None:
            return page
        where = ["p.text_key IS NOT NULL"]
        if q.strip():
            # contains() rather than LIKE, so % and _ in a search mean themselves.
            where.append(f"contains(lower(p.file_name), lower({literal(q.strip())}))")
        if chunker_id:
            where.append(
                "EXISTS (SELECT 1 FROM chunks c WHERE c.paper_id = p.paper_id "
                f"AND c.chunker_id = {literal(chunker_id)})"
            )
        scope = " AND ".join(where)
        total = self._rows.query(
            f"SELECT count(*) AS total FROM papers p WHERE {scope}"  # nosec B608
        )
        page["total"] = int(total[0]["total"]) if total else 0
        rows = self._rows.query(
            "SELECT p.paper_id, p.file_name, p.storage_prefix, p.storage_key, "  # nosec B608
            f"p.discovered_at FROM papers p WHERE {scope} "
            "ORDER BY lower(p.file_name), p.paper_id "
            f"LIMIT {int(limit)} OFFSET {int(offset)}"
        )
        counts = self._chunk_counts([row["paper_id"] for row in rows])
        page["papers"] = [
            {
                "paper_id": row["paper_id"],
                "file_name": row["file_name"],
                "storage_prefix": row["storage_prefix"],
                "storage_key": row["storage_key"],
                "discovered_at": _iso(row["discovered_at"]),
                "chunks": counts.get(row["paper_id"], {}),
            }
            for row in rows
        ]
        return page

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


def _preview(head: str, chars: int) -> str:
    text = " ".join(head.split())
    if len(text) <= PREVIEW_CHARS and chars <= len(head):
        return text
    return text[:PREVIEW_CHARS].rstrip() + "…"


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
