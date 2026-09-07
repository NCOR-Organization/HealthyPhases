"""Splitting papers into the units extraction runs against.

A chunk belongs to a paper *and* to the mechanism that cut it, so two
mechanisms can run over the same corpus and their chunks sit side by side
rather than one replacing the other.

Re-running a mechanism over a paper it has already chunked does nothing: the
outstanding set is computed once per run, so an unchanged corpus costs one
query and no reads.
"""

from __future__ import annotations

from phases_v2 import identity
from phases_v2.chunking.interfaces import (
    ChunkingMechanism,
    ChunkRecord,
    ChunkReport,
    ChunkStore,
    TextSource,
)


def chunk_papers(
    *,
    chunker_id: str,
    mechanism: ChunkingMechanism,
    texts: TextSource,
    chunks: ChunkStore,
    paper_ids: list[str] | None = None,
) -> ChunkReport:
    """Chunk every paper this mechanism has not chunked yet."""
    outstanding = chunks.outstanding_papers(chunker_id, paper_ids)
    report = ChunkReport(papers_considered=len(outstanding))
    if not outstanding:
        return report

    records: list[ChunkRecord] = []
    for paper in outstanding:
        text = texts.read_text(paper.text_key)
        pieces = mechanism.split(text)
        if not pieces:
            report.papers_skipped += 1
            continue
        report.papers_chunked += 1
        for seq, (piece, char_start, char_end) in enumerate(pieces):
            records.append(
                ChunkRecord(
                    chunk_id=identity.chunk_id(paper.paper_id, chunker_id, seq),
                    paper_id=paper.paper_id,
                    chunker_id=chunker_id,
                    seq=seq,
                    text=piece,
                    char_start=char_start,
                    char_end=char_end,
                    token_count=len(piece.split()),
                )
            )

    if records:
        chunks.save(records)
    report.chunks_written = len(records)
    return report
