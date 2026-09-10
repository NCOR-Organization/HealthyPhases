"""Wiring for the projectors.

The run pins one catalog snapshot and reads everything at it. Snapshots are
catalog-wide, so this gives a coherent view across every dataset the projection
touches — which is what stops a run seeing an extraction whose items have not
landed yet.
"""

from __future__ import annotations

from phases_v2.datasets.row_store import DatasetRowStore
from phases_v2.projection.adapters.secondary.DatasetExtractionReader import (
    DatasetExtractionReader,
)
from phases_v2.projection.adapters.secondary.DatasetProjectionLedger import (
    DatasetProjectionLedger,
)
from phases_v2.projection.adapters.secondary.TripleStoreSink import TripleStoreSink
from phases_v2.projection.graph import project_graph
from phases_v2.projection.interfaces import ProjectionReport, TripleSink


def project_to_graph(engine, sink: TripleSink | None = None) -> ProjectionReport:
    live = DatasetRowStore(engine.services.dataset)
    pinned = live.at_snapshot(live.snapshot())

    return project_graph(
        reader=DatasetExtractionReader(pinned),
        sink=sink if sink is not None else TripleStoreSink(engine.services.triple_store),
        # The ledger records the present, so it is not pinned.
        ledger=DatasetProjectionLedger(live),
    )


def project_to_vectors(
    engine, sink=None, embedder=None
) -> ProjectionReport:
    """Embed outstanding chunks and items, reading at one pinned snapshot."""
    from phases_v2.projection.adapters.secondary.VectorStoreSink import VectorStoreSink
    from phases_v2.projection.embedding_factory import embedder_for
    from phases_v2.projection.vectors import project_vectors

    live = DatasetRowStore(engine.services.dataset)
    pinned = live.at_snapshot(live.snapshot())

    return project_vectors(
        reader=DatasetExtractionReader(pinned),
        embedder=embedder if embedder is not None else embedder_for(engine),
        sink=sink if sink is not None else VectorStoreSink(engine.services.vector_store),
        ledger=DatasetProjectionLedger(live),
    )
