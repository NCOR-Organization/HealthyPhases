"""The ``papers`` and ``chunks`` datasets, as the domain's :class:`ChunkStore`."""

from __future__ import annotations

from phases_v2.chunking.interfaces import ChunkRecord, PaperText
from phases_v2.ports import RowStore
from phases_v2.sql import in_list, literal


class DatasetChunkStore:
    def __init__(self, rows: RowStore):
        self._rows = rows

    def outstanding_papers(
        self, chunker_id: str, paper_ids: list[str] | None = None
    ) -> list[PaperText]:
        # One anti-join rather than a lookup per paper: an unchanged corpus
        # then costs a single query.
        scope = (
            f"AND p.paper_id IN {in_list(paper_ids)}" if paper_ids is not None else ""
        )
        sql = f"""
            SELECT p.paper_id, p.text_key
            FROM papers p
            LEFT JOIN (
                SELECT DISTINCT paper_id
                FROM chunks
                WHERE chunker_id = {literal(chunker_id)}
            ) c ON c.paper_id = p.paper_id
            WHERE p.text_key IS NOT NULL
              AND c.paper_id IS NULL
              {scope}
            ORDER BY p.paper_id
        """  # nosec B608 - every interpolated value goes through sql.literal
        return [
            PaperText(paper_id=row["paper_id"], text_key=row["text_key"])
            for row in self._rows.query(sql)
        ]

    def save(self, chunks: list[ChunkRecord]) -> None:
        self._rows.write_rows(
            "chunks",
            [
                {
                    "chunk_id": chunk.chunk_id,
                    "paper_id": chunk.paper_id,
                    "chunker_id": chunk.chunker_id,
                    "seq": chunk.seq,
                    "text": chunk.text,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "token_count": chunk.token_count,
                }
                for chunk in chunks
            ],
        )
