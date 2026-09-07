"""The extraction datasets, as the domain's :class:`ExtractionStore`.

The outstanding-work query is the anti-join from design D4. It is one query per
run rather than a lookup per chunk, which is what makes re-running a finished
corpus cost almost nothing.
"""

from __future__ import annotations

from phases_v2.extraction.interfaces import (
    SUCCEEDED,
    ChunkRef,
    ExtractedItemRecord,
    ExtractionRecord,
    RunRecord,
)
from phases_v2.ports import RowStore
from phases_v2.sql import in_list, literal


class DatasetExtractionStore:
    def __init__(self, rows: RowStore):
        self._rows = rows

    def outstanding_chunks(
        self,
        *,
        chunker_id: str,
        model_id: str,
        prompt_id: str,
        paper_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[ChunkRef]:
        scope = (
            f"AND c.paper_id IN {in_list(paper_ids)}" if paper_ids is not None else ""
        )
        bound = f"LIMIT {int(limit)}" if limit is not None else ""
        sql = f"""
            SELECT c.chunk_id, c.paper_id, c.text
            FROM chunks c
            LEFT JOIN extractions e
              ON  e.chunk_id  = c.chunk_id
              AND e.model_id  = {literal(model_id)}
              AND e.prompt_id = {literal(prompt_id)}
              AND e.status    = {literal(SUCCEEDED)}
            WHERE c.chunker_id = {literal(chunker_id)}
              AND e.extraction_id IS NULL
              {scope}
            ORDER BY c.chunk_id
            {bound}
        """  # nosec B608 - every interpolated value goes through sql.literal
        return [
            ChunkRef(
                chunk_id=row["chunk_id"], paper_id=row["paper_id"], text=row["text"]
            )
            for row in self._rows.query(sql)
        ]

    def count_candidates(
        self, *, chunker_id: str, paper_ids: list[str] | None = None
    ) -> int:
        scope = (
            f"AND paper_id IN {in_list(paper_ids)}" if paper_ids is not None else ""
        )
        sql = f"""
            SELECT count(*) AS total
            FROM chunks
            WHERE chunker_id = {literal(chunker_id)}
            {scope}
        """  # nosec B608 - every interpolated value goes through sql.literal
        return int(self._rows.query(sql)[0]["total"])

    def save_items(self, items: list[ExtractedItemRecord]) -> None:
        self._rows.write_rows(
            "extracted_items",
            [
                {
                    "item_id": item.item_id,
                    "extraction_id": item.extraction_id,
                    "chunk_id": item.chunk_id,
                    "paper_id": item.paper_id,
                    "prompt_id": item.prompt_id,
                    "seq": item.seq,
                    "text": item.text,
                }
                for item in items
            ],
        )

    def save_extractions(self, extractions: list[ExtractionRecord]) -> None:
        self._rows.write_rows(
            "extractions",
            [
                {
                    "extraction_id": record.extraction_id,
                    "chunk_id": record.chunk_id,
                    "model_id": record.model_id,
                    "prompt_id": record.prompt_id,
                    "run_id": record.run_id,
                    "status": record.status,
                    "response": record.response,
                    "raw_response": record.raw_response,
                    "error": record.error,
                    "item_count": record.item_count,
                    "completed_at": record.completed_at,
                }
                for record in extractions
            ],
        )

    def save_run(self, run: RunRecord) -> None:
        self._rows.write_rows(
            "extraction_runs",
            [
                {
                    "run_id": run.run_id,
                    "chunker_id": run.chunker_id,
                    "model_id": run.model_id,
                    "prompt_id": run.prompt_id,
                    "started_at": run.started_at,
                    "finished_at": run.finished_at,
                    "succeeded": run.succeeded,
                    "failed": run.failed,
                    "skipped": run.skipped,
                }
            ],
        )
