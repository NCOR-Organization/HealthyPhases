"""Projecting the datasets into this module's named graphs.

Three separate properties, three mechanisms:

* **Idempotent** — RDF is a set and every URI is content-addressed, so
  re-inserting the same row's triples changes nothing.
* **Incremental** — the ``projections`` ledger records what has been projected,
  so a re-run does no work rather than merely no harm.
* **Coherent** — the caller pins one snapshot and the reader serves everything
  from it, so a write landing mid-run cannot produce a projection that mixes
  state from before and after it.

The ledger is written *after* the triples. A crash between them leaves the row
unrecorded and it is projected again next time, which RDF absorbs. The reverse
order would lose the triples permanently.
"""

from __future__ import annotations

import rdflib

from phases_v2.ontologies import vocabulary as v
from phases_v2.projection.interfaces import (
    GRAPH,
    ExtractionReader,
    ProjectionLedger,
    ProjectionReport,
    TripleSink,
)


def project_graph(
    *,
    reader: ExtractionReader,
    sink: TripleSink,
    ledger: ProjectionLedger,
) -> ProjectionReport:
    """Project every succeeded extraction that has not been projected yet."""
    extractions = reader.succeeded_extractions()
    done = ledger.projected_keys(GRAPH)
    outstanding = [e for e in extractions if e["extraction_id"] not in done]

    report = ProjectionReport(
        already_projected=len(extractions) - len(outstanding),
    )
    if not outstanding:
        return report

    ids = [e["extraction_id"] for e in outstanding]
    items = reader.items_for(ids)
    chunk_ids = {e["chunk_id"] for e in outstanding}

    _project_corpus(reader, sink, chunk_ids)
    _project_extractions(sink, outstanding, items)

    ledger.record(GRAPH, ids)
    report.projected = len(outstanding)
    return report


def _project_corpus(
    reader: ExtractionReader, sink: TripleSink, chunk_ids: set[str]
) -> None:
    """Papers and chunks the outstanding extractions refer to."""
    chunks = [chunk for chunk in reader.chunks() if chunk["chunk_id"] in chunk_ids]
    paper_ids = {chunk["paper_id"] for chunk in chunks}
    papers = [paper for paper in reader.papers() if paper["paper_id"] in paper_ids]

    triples: list[tuple] = []
    for paper in papers:
        uri = v.paper_uri(paper["paper_id"])
        triples.append((uri, rdflib.RDF.type, v.DOC.PDFPaperFile))
        if paper.get("file_name"):
            triples.append(
                (uri, v.DOC.file_name, rdflib.Literal(paper["file_name"]))
            )

    for chunk in chunks:
        uri = v.chunk_uri(chunk["chunk_id"])
        triples.extend(
            [
                (uri, rdflib.RDF.type, v.DOC.Chunk),
                (uri, v.DOC.belongs_to, v.paper_uri(chunk["paper_id"])),
                (uri, v.DOC.chunk_text, rdflib.Literal(chunk["text"])),
                (uri, v.DOC.item_number, rdflib.Literal(chunk["seq"])),
            ]
        )
        if chunk.get("chunker_id"):
            triples.append(
                (uri, v.DOC.chunker_id, rdflib.Literal(chunk["chunker_id"]))
            )

    if triples:
        sink.insert(str(v.PAPERS_GRAPH), triples)


def _project_extractions(
    sink: TripleSink, extractions: list[dict], items: list[dict]
) -> None:
    triples: list[tuple] = []

    for extraction in extractions:
        uri = v.extraction_uri(extraction["extraction_id"])
        triples.extend(
            [
                (uri, rdflib.RDF.type, v.DOC.Extraction),
                (
                    uri,
                    v.DOC.extraction_id,
                    rdflib.Literal(extraction["extraction_id"]),
                ),
                (
                    uri,
                    v.DOC.extracted_from_chunk,
                    v.chunk_uri(extraction["chunk_id"]),
                ),
                (uri, v.DOC.model_name, rdflib.Literal(extraction["model_id"])),
                # Provenance: which prompt version produced this.
                (uri, v.DOC.prompt_hash, rdflib.Literal(extraction["prompt_id"])),
            ]
        )

    for item in items:
        uri = v.item_uri(item["item_id"])
        triples.extend(
            [
                (uri, rdflib.RDF.type, v.DOC.ExtractedItem),
                (uri, v.DOC.extracted_item_id, rdflib.Literal(item["item_id"])),
                (uri, v.DOC.extracted_text, rdflib.Literal(item["text"])),
                (uri, v.DOC.item_number, rdflib.Literal(item["seq"])),
                (uri, v.DOC.extracted_by, v.extraction_uri(item["extraction_id"])),
                (uri, v.DOC.extracted_from_chunk, v.chunk_uri(item["chunk_id"])),
                (uri, v.DOC.belongs_to, v.paper_uri(item["paper_id"])),
            ]
        )

    if triples:
        sink.insert(str(v.EXTRACTIONS_GRAPH), triples)
