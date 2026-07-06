"""Domain models for the reverse-search application.

These are intentionally free of any storage/technology concern. They double as
the FastAPI request/response schemas (pydantic), which keeps the primary
adapter thin.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


class ItemLocation(BaseModel):
    """Where an extracted item lives in the corpus.

    The only location granularity the knowledge graph stores today is the
    source paper (``paper_path``) and the chunk position within it
    (``chunk_number``). There are no page numbers or character offsets — the
    chunk text is returned so a researcher can ground the claim in context.
    """

    pipeline: str | None = Field(
        default=None,
        description="Extraction pipeline that produced the item "
        "(causes / how / when / where / effects / logical_sentences / ...).",
    )
    model: str | None = Field(
        default=None, description="LLM that produced the extraction."
    )
    chunk_id: str | None = Field(default=None)
    chunk_number: int | None = Field(
        default=None, description="0-based position of the chunk within the paper."
    )
    chunk_text: str | None = Field(
        default=None, description="Full text of the source chunk (surrounding context)."
    )
    paper_path: str | None = Field(default=None)

    @property
    def paper_name(self) -> str | None:
        if not self.paper_path:
            return None
        return os.path.basename(self.paper_path)


class SearchHit(BaseModel):
    """A single reverse-search result."""

    extracted_item_id: str
    extracted_text: str
    score: float | None = Field(
        default=None,
        description="Cosine similarity for semantic hits; null for keyword hits.",
    )
    pipeline: str | None = None
    model: str | None = None
    chunk_id: str | None = None
    chunk_number: int | None = None
    chunk_text: str | None = None
    paper_path: str | None = None
    paper_name: str | None = None

    @classmethod
    def build(
        cls,
        *,
        extracted_item_id: str,
        extracted_text: str,
        location: ItemLocation | None,
        score: float | None = None,
    ) -> "SearchHit":
        loc = location or ItemLocation()
        return cls(
            extracted_item_id=extracted_item_id,
            extracted_text=extracted_text,
            score=score,
            pipeline=loc.pipeline,
            model=loc.model,
            chunk_id=loc.chunk_id,
            chunk_number=loc.chunk_number,
            chunk_text=loc.chunk_text,
            paper_path=loc.paper_path,
            paper_name=loc.paper_name,
        )


class SemanticMatch(BaseModel):
    """Raw output of the semantic index port, before KG enrichment."""

    extracted_item_id: str
    text: str
    score: float


class SearchResponse(BaseModel):
    query: str
    mode: str
    count: int
    hits: list[SearchHit]


class PipelinesResponse(BaseModel):
    pipelines: list[str]
