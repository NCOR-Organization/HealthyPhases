"""Reads the pipeline's datasets for a projection run.

Every read goes through the same :class:`RowStore`, so pinning that store to a
snapshot pins the whole run: papers, chunks, extractions and items are all
observed at one instant, and an extraction can never be seen without the items
that belong to it.
"""

from __future__ import annotations

from typing import Any

from phases_v2.extraction.interfaces import SUCCEEDED
from phases_v2.ports import RowStore
from phases_v2.sql import in_list, literal


class DatasetExtractionReader:
    def __init__(self, rows: RowStore):
        self._rows = rows

    def papers(self) -> list[dict[str, Any]]:
        return self._rows.query("SELECT paper_id, file_name FROM papers")

    def chunks(self) -> list[dict[str, Any]]:
        return self._rows.query(
            "SELECT chunk_id, paper_id, chunker_id, seq, text FROM chunks"
        )

    def succeeded_extractions(self) -> list[dict[str, Any]]:
        return self._rows.query(
            "SELECT extraction_id, chunk_id, model_id, prompt_id, item_count "
            f"FROM extractions WHERE status = {literal(SUCCEEDED)} "
            "ORDER BY extraction_id"
        )

    def items_for(self, extraction_ids: list[str]) -> list[dict[str, Any]]:
        if not extraction_ids:
            return []
        sql = (
            "SELECT item_id, extraction_id, chunk_id, paper_id, prompt_id, seq, text "
            f"FROM extracted_items WHERE extraction_id IN {in_list(extraction_ids)} "
            "ORDER BY extraction_id, seq"
        )  # nosec B608 - every interpolated value goes through sql.literal
        return self._rows.query(sql)
