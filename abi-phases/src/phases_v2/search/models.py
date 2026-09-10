"""Domain value objects for reverse search.

Free of any storage/technology concern, like every other domain's models in
this module. Plain frozen dataclasses, not pydantic — the primary adapter is
what turns these into JSON (see ``app/adapters/primary/SearchAPI.py``), the
same split ``requests.interfaces.RunRequest`` uses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ItemLocation:
    """Where an extracted item lives in the corpus.

    The only location granularity the datasets record is the source paper and
    the chunk position within it (``chunk_seq``) — there are no page numbers or
    character offsets, so ``chunk_text`` is carried along so a researcher can
    ground the claim in context.
    """

    prompt_id: str | None = None
    prompt_name: str | None = None
    model_id: str | None = None
    chunk_id: str | None = None
    chunk_seq: int | None = None
    chunk_text: str | None = None
    paper_id: str | None = None
    paper_name: str | None = None
    source_path: str | None = None
    prompt_template: str | None = None


@dataclass(frozen=True)
class SearchHit:
    """A single reverse-search result."""

    item_id: str
    extracted_text: str
    score: float | None = None
    prompt_id: str | None = None
    prompt_name: str | None = None
    model_id: str | None = None
    chunk_id: str | None = None
    chunk_seq: int | None = None
    chunk_text: str | None = None
    paper_id: str | None = None
    paper_name: str | None = None
    source_path: str | None = None
    prompt_template: str | None = None

    @classmethod
    def build(
        cls,
        *,
        item_id: str,
        extracted_text: str,
        location: ItemLocation | None,
        score: float | None = None,
    ) -> SearchHit:
        loc = location or ItemLocation()
        return cls(
            item_id=item_id,
            extracted_text=extracted_text,
            score=score,
            prompt_id=loc.prompt_id,
            prompt_name=loc.prompt_name,
            model_id=loc.model_id,
            chunk_id=loc.chunk_id,
            chunk_seq=loc.chunk_seq,
            chunk_text=loc.chunk_text,
            paper_id=loc.paper_id,
            paper_name=loc.paper_name,
            source_path=loc.source_path,
            prompt_template=loc.prompt_template,
        )


@dataclass(frozen=True)
class SemanticMatch:
    """Raw output of the semantic index port, before location enrichment."""

    item_id: str
    text: str
    score: float
