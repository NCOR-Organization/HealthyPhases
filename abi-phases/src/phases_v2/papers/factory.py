"""Wiring for paper ingestion.

The domain takes its collaborators as arguments; this is the one place that
knows which real implementations to hand it.
"""

from __future__ import annotations

from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.papers.adapters.secondary.DatasetPaperStore import DatasetPaperStore
from phases_v2.papers.adapters.secondary.ObjectStorageSource import (
    ObjectStorageSource,
)
from phases_v2.papers.adapters.secondary.PdfTextRenderer import PdfTextRenderer
from phases_v2.papers.domain import ingest
from phases_v2.papers.interfaces import IngestReport


def ingest_papers(engine, locations: list[str], artifacts=None) -> IngestReport:
    """Ingest every paper beneath ``locations`` using the engine's services."""
    from phases_v2.sources.adapters.secondary.phases_v2_artifact_source import (
        ManifestSource,
    )

    return ingest(
        locations,
        source=(
            ManifestSource(engine.services.object_storage, artifacts)
            if artifacts is not None
            else ObjectStorageSource(engine.services.object_storage)
        ),
        renderer=PdfTextRenderer(),
        papers=DatasetPaperStore(DatasetRowStore(engine.services.dataset)),
    )
