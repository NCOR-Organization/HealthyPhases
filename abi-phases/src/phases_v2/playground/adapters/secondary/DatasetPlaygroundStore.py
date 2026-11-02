"""The pipeline's datasets, read as the playground's :class:`PlaygroundStore`.

Queries only. The row store is never written through from here.
"""

from __future__ import annotations

import json

from phases_v2.playground.domain import baseline_extraction_ids
from phases_v2.playground.interfaces import PaperChunk, StoredExtraction
from phases_v2.ports import RowStore
from phases_v2.prompts.domain import PromptTemplate
from phases_v2.prompts.templates import declared_prompts
from phases_v2.sql import in_list, literal


class DatasetPlaygroundStore:
    def __init__(self, rows: RowStore):
        self._rows = rows

    def prompt(self, prompt_id: str) -> PromptTemplate | None:
        found = self._rows.query(
            "SELECT name, template, output_key FROM prompts "  # nosec B608
            f"WHERE prompt_id = {literal(prompt_id)}"
        )
        if found:
            return PromptTemplate(**found[0])
        return next((p for p in declared_prompts() if p.prompt_id == prompt_id), None)

    def is_ingested(self, paper_id: str) -> bool:
        return bool(
            self._rows.query(
                "SELECT paper_id FROM papers "  # nosec B608
                f"WHERE paper_id = {literal(paper_id)} AND text_key IS NOT NULL "
                "LIMIT 1"
            )
        )

    def chunk_counts(self, paper_id: str) -> dict[str, int]:
        rows = self._rows.query(
            "SELECT chunker_id, count(*) AS chunks FROM chunks "  # nosec B608
            f"WHERE paper_id = {literal(paper_id)} GROUP BY chunker_id"
        )
        return {row["chunker_id"]: int(row["chunks"]) for row in rows}

    def chunks(
        self,
        paper_id: str,
        chunker_id: str,
        *,
        seqs: list[int] | None = None,
        first: int | None = None,
    ) -> list[PaperChunk]:
        scope = (
            f"AND seq IN ({', '.join(str(int(seq)) for seq in seqs)})" if seqs else ""
        )
        bound = f"LIMIT {int(first)}" if first is not None and not seqs else ""
        rows = self._rows.query(
            "SELECT seq, chunk_id, paper_id, text FROM chunks "  # nosec B608
            f"WHERE paper_id = {literal(paper_id)} "
            f"AND chunker_id = {literal(chunker_id)} {scope} "
            f"ORDER BY seq {bound}"
        )
        return [
            PaperChunk(
                seq=int(row["seq"]),
                chunk_id=row["chunk_id"],
                paper_id=row["paper_id"],
                text=row["text"] or "",
            )
            for row in rows
        ]

    def stored(
        self, chunk_ids: list[str], *, model_id: str, prompt_id: str
    ) -> dict[str, StoredExtraction]:
        ids = baseline_extraction_ids(chunk_ids, model_id=model_id, prompt_id=prompt_id)
        extractions = self._rows.query(
            "SELECT extraction_id, chunk_id, status, error FROM extractions "  # nosec B608
            f"WHERE prompt_id = {literal(prompt_id)} AND extraction_id IN {in_list(ids)}"
        )
        if not extractions:
            return {}
        items: dict[str, list[str]] = {}
        for row in self._rows.query(
            "SELECT extraction_id, seq, text FROM extracted_items "  # nosec B608
            f"WHERE prompt_id = {literal(prompt_id)} AND extraction_id IN {in_list(ids)} "
            "ORDER BY extraction_id, seq"
        ):
            items.setdefault(row["extraction_id"], []).append(
                row["text"]
                if isinstance(row["text"], str)
                else json.dumps(row["text"], ensure_ascii=False)
            )
        return {
            row["chunk_id"]: StoredExtraction(
                status=row["status"],
                error=row["error"],
                items=items.get(row["extraction_id"], []),
            )
            for row in extractions
        }
