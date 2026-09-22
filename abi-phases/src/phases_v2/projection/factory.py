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


def project_to_graph(
    engine, sink: TripleSink | None = None, paper_ids=None
) -> ProjectionReport:
    live = DatasetRowStore(engine.services.dataset)
    pinned = live.at_snapshot(live.snapshot())

    return project_graph(
        reader=DatasetExtractionReader(pinned, paper_ids=paper_ids),
        sink=sink
        if sink is not None
        else TripleStoreSink(engine.services.triple_store),
        # The ledger records the present, so it is not pinned.
        ledger=DatasetProjectionLedger(live),
    )


def project_to_vectors(
    engine, sink=None, embedder=None, paper_ids=None
) -> ProjectionReport:
    """Embed outstanding chunks and items, reading at one pinned snapshot."""
    from phases_v2.projection.adapters.secondary.VectorStoreSink import VectorStoreSink
    from phases_v2.projection.embedding_factory import embedder_for
    from phases_v2.projection.vectors import project_vectors

    live = DatasetRowStore(engine.services.dataset)
    pinned = live.at_snapshot(live.snapshot())

    return project_vectors(
        reader=DatasetExtractionReader(pinned, paper_ids=paper_ids),
        embedder=embedder if embedder is not None else embedder_for(engine),
        sink=sink
        if sink is not None
        else VectorStoreSink(engine.services.vector_store),
        ledger=DatasetProjectionLedger(live),
    )


def refresh_vector_metadata(engine) -> int:
    from naas_abi_core.services.vector_store.adapters.QdrantAdapter import QdrantAdapter

    from phases_v2.projection.adapters.secondary.QdrantMetadataSink import (
        QdrantMetadataSink,
    )
    from phases_v2.projection.metadata_refresh import refresh_metadata

    store = engine.services.vector_store
    if not isinstance(store.adapter, QdrantAdapter):
        raise TypeError("Vector metadata refresh requires Qdrant")
    store.initialize()
    live = DatasetRowStore(engine.services.dataset)
    return refresh_metadata(
        DatasetExtractionReader(live.at_snapshot(live.snapshot())),
        QdrantMetadataSink(store.adapter.client),
    )


def project_to_relations(
    engine, *, dry_run: bool = False, paper_ids=None, reproject: bool = False
):
    from phases_v2.projection.adapters.secondary.ProbabilisticContractValidator import (
        validate_relation,
    )
    from phases_v2.projection.probabilistic import project_relations

    live = DatasetRowStore(engine.services.dataset)
    return project_relations(
        live.at_snapshot(live.snapshot()),
        live,
        validate_relation,
        dry_run=dry_run,
        paper_ids=paper_ids,
        reproject=reproject,
    )


def rebuild_relations(engine):
    """Recreate ``probabilistic_relations`` and derive every row again.

    For a change to the row shape: the old table cannot take the new columns,
    and the ledger already records every item. Reads saved extractions only;
    no model is called.
    """
    from phases_v2.datasets.store import recreate

    recreate(engine.services.dataset, "probabilistic_relations")
    return project_to_relations(engine, reproject=True)
