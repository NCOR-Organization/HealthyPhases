"""Wiring for extraction.

The chat model comes from the engine's model registry, routed by the provider
the catalog declares. Passing ``provider=`` lets the registry build an
off-catalog model through that provider's factory, so this module can declare
models the registry has no explicit entry for.
"""

from __future__ import annotations

from phases_v2.chunking.chunkers import WINDOW_512_128, Chunker
from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.extraction.adapters.secondary.DatasetExtractionStore import (
    DatasetExtractionStore,
)
from phases_v2.extraction.adapters.secondary.LangchainExtractionModel import (
    LangchainExtractionModel,
)
from phases_v2.extraction.domain import run_extraction
from phases_v2.extraction.interfaces import ExtractionModel, ExtractionReport
from phases_v2.models.catalog import resolve as resolve_model
from phases_v2.prompts.domain import PromptTemplate
from phases_v2.prompts.templates import declared_prompts


def resolve_prompt(prompt_id: str) -> PromptTemplate:
    for template in declared_prompts():
        if template.prompt_id == prompt_id:
            return template
    raise ValueError(
        f"{prompt_id!r} is not a declared prompt; declared prompts are "
        + ", ".join(t.prompt_id for t in declared_prompts())
    )


def model_for(engine, model_id: str, output_key: str = "results") -> ExtractionModel:
    """Build the chat model a declared catalog entry describes."""
    declaration = resolve_model(model_id)
    registered = engine.services.model_registry.get(
        declaration.provider_model_id, provider=declaration.provider
    )
    return LangchainExtractionModel(registered.model, output_key)


def extract(
    engine,
    *,
    model_id: str,
    prompt_id: str,
    chunker: Chunker = WINDOW_512_128,
    paper_ids: list[str] | None = None,
    max_chunks: int | None = None,
    model: ExtractionModel | None = None,
    run_id: str | None = None,
    workers: int = 20,
) -> ExtractionReport:
    """Run one prompt over the outstanding chunks for one model.

    ``resolve_model`` and ``resolve_prompt`` run before anything is written, so
    a run naming something undeclared fails without leaving rows behind.
    """
    prompt = resolve_prompt(prompt_id)
    resolve_model(model_id)

    return run_extraction(
        store=DatasetExtractionStore(DatasetRowStore(engine.services.dataset)),
        model=model
        if model is not None
        else model_for(engine, model_id, prompt.output_key),
        prompt=prompt,
        model_id=model_id,
        chunker_id=chunker.chunker_id,
        paper_ids=paper_ids,
        max_chunks=max_chunks,
        run_id=run_id,
        workers=workers,
    )
