"""Wiring for the coverage report: the real reader, pinned to one snapshot."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from phases_v2.chunking.chunkers import DECLARED_CHUNKERS
from phases_v2.coverage.domain import CoverageReport, build_report
from phases_v2.coverage.interfaces import DEFAULT_MODEL, Selection
from phases_v2.prompts.templates import current_prompts, declared_prompts


def selection(
    models: Sequence[str] = (),
    prompt_ids: Sequence[str] = (),
    chunker_id: str | None = None,
) -> Selection:
    """What to check. By default the current version of every declared prompt,
    with :data:`DEFAULT_MODEL`, on chunks cut by the declared chunker."""
    return Selection(
        models=tuple(dict.fromkeys(models)) or (DEFAULT_MODEL,),
        prompt_ids=tuple(dict.fromkeys(prompt_ids))
        or tuple(p.prompt_id for p in current_prompts()),
        chunker_id=chunker_id or DECLARED_CHUNKERS[0].chunker_id,
    )


def coverage_report(
    dataset: Any, object_storage: Any, chosen: Selection
) -> CoverageReport:
    """Read the whole report at the dataset's current snapshot."""
    from phases_v2.coverage.adapters.secondary.DatasetCoverageReader import (
        DatasetCoverageReader,
        PinnedDataset,
    )
    from phases_v2.datasets.row_store import DatasetRowStore
    from phases_v2.papers.adapters.secondary.PdfTextRenderer import PdfTextRenderer
    from phases_v2.sources.adapters.secondary.phases_v2_pubmed_catalog import (
        PubmedCatalog,
    )

    live = DatasetRowStore(dataset)
    snapshot = live.snapshot()
    reader = DatasetCoverageReader(
        # A pinned store refuses writes as well as reading at one instant.
        live.at_snapshot(snapshot),
        snapshot=snapshot,
        pubmed=PubmedCatalog(PinnedDataset(dataset, snapshot)),
        storage=object_storage,
        supported=PdfTextRenderer().handles,
    )
    return build_report(
        reader, chosen, declared=declared_prompts(), current=current_prompts()
    )
