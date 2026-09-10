"""Embedding chunks and extracted items into this module's collections.

Same three properties as the graph projector, but the balance differs:
embedding is the expensive step, so the ledger is not an optimisation here —
it is the difference between a free re-run and paying to embed the corpus
again.

Vector ids are the content-addressed row ids, and the store upserts by id, so
re-storing a doc replaces rather than duplicates. The ledger is written after
the vectors: a crash between them re-embeds a few rows, which costs money but
cannot corrupt anything. The reverse order would silently skip rows forever.
"""

from __future__ import annotations

from phases_v2.projection.interfaces import (
    VECTOR_CHUNKS,
    VECTOR_ITEMS,
    Embedder,
    ExtractionReader,
    ProjectionLedger,
    ProjectionReport,
    VectorDoc,
    VectorSink,
)

CHUNKS_COLLECTION = "phases_v2_chunks"
ITEMS_COLLECTION = "phases_v2_extracted_items"
# Checkpoint after each batch so a later API/storage failure can resume cheaply.
PROJECTION_BATCH_SIZE = 128


def project_vectors(
    *,
    reader: ExtractionReader,
    embedder: Embedder,
    sink: VectorSink,
    ledger: ProjectionLedger,
) -> ProjectionReport:
    """Embed every chunk and item that has not been embedded yet."""
    sink.ensure_collection(CHUNKS_COLLECTION, embedder.dimension)
    sink.ensure_collection(ITEMS_COLLECTION, embedder.dimension)

    report = ProjectionReport()
    extractions = {e["extraction_id"]: e for e in reader.succeeded_extractions()}

    report = _project(
        target=VECTOR_CHUNKS,
        collection=CHUNKS_COLLECTION,
        docs=[
            VectorDoc(
                id=chunk["chunk_id"],
                text=chunk["text"],
                metadata={
                    "chunk_id": chunk["chunk_id"],
                    "paper_id": chunk["paper_id"],
                    "chunker_id": chunk.get("chunker_id"),
                    "seq": chunk.get("seq"),
                },
            )
            for chunk in reader.chunks()
        ],
        embedder=embedder,
        sink=sink,
        ledger=ledger,
        report=report,
    )

    items = reader.items_for(list(extractions))
    return _project(
        target=VECTOR_ITEMS,
        collection=ITEMS_COLLECTION,
        docs=[
            VectorDoc(
                id=item["item_id"],
                text=item["text"],
                metadata={
                    "item_id": item["item_id"],
                    "extraction_id": item["extraction_id"],
                    "chunk_id": item["chunk_id"],
                    "paper_id": item["paper_id"],
                    "prompt_id": item["prompt_id"],
                    # A search hit must say which model produced the claim.
                    "model_id": extractions.get(item["extraction_id"], {}).get(
                        "model_id"
                    ),
                    "seq": item.get("seq"),
                },
            )
            for item in items
        ],
        embedder=embedder,
        sink=sink,
        ledger=ledger,
        report=report,
    )


def _project(
    *,
    target: str,
    collection: str,
    docs: list[VectorDoc],
    embedder: Embedder,
    sink: VectorSink,
    ledger: ProjectionLedger,
    report: ProjectionReport,
) -> ProjectionReport:
    done = ledger.projected_keys(target)
    outstanding = [doc for doc in docs if doc.id not in done]
    report.already_projected += len(docs) - len(outstanding)
    if not outstanding:
        return report

    for start in range(0, len(outstanding), PROJECTION_BATCH_SIZE):
        batch = outstanding[start : start + PROJECTION_BATCH_SIZE]
        vectors = embedder.embed([doc.text for doc in batch])
        if len(vectors) != len(batch):
            raise ValueError(
                "embedder returned a different number of vectors than documents"
            )
        sink.store(collection, batch, vectors)
        ledger.record(target, [doc.id for doc in batch])
        report.projected += len(batch)
    return report
