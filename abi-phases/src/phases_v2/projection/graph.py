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

Outstanding extractions are written in batches of ``BATCH_SIZE``, each batch's
ledger entries right after its triples. One insert of a whole corpus can take
longer than the triple store's request timeout, and the store then rejects the
cut-off request; in batches each insert stays small, and a run that stops part
way keeps what it wrote.
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

#: Extractions per insert. A thousand, with their items and chunks, is a few
#: megabytes of SPARQL: seconds for the store, far inside its timeout.
BATCH_SIZE = 1000


def project_graph(
    *,
    reader: ExtractionReader,
    sink: TripleSink,
    ledger: ProjectionLedger,
    batch_size: int = BATCH_SIZE,
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

    chunks = {chunk["chunk_id"]: chunk for chunk in reader.chunks()}
    papers = {paper["paper_id"]: paper for paper in reader.papers()}
    for start in range(0, len(outstanding), batch_size):
        batch = outstanding[start : start + batch_size]
        ids = [e["extraction_id"] for e in batch]
        _project_corpus(sink, chunks, papers, {e["chunk_id"] for e in batch})
        _project_extractions(sink, batch, reader.items_for(ids))
        ledger.record(GRAPH, ids)
        report.projected += len(batch)
    return report


def _project_corpus(
    sink: TripleSink,
    chunks_by_id: dict[str, dict],
    papers_by_id: dict[str, dict],
    chunk_ids: set[str],
) -> None:
    """Papers and chunks the given extractions refer to."""
    chunks = [chunks_by_id[c] for c in sorted(chunk_ids) if c in chunks_by_id]
    paper_ids = {chunk["paper_id"] for chunk in chunks}
    papers = [papers_by_id[p] for p in sorted(paper_ids) if p in papers_by_id]

    triples: list[tuple] = []
    for paper in papers:
        uri = v.paper_uri(paper["paper_id"])
        triples.append((uri, rdflib.RDF.type, v.DOC.PDFPaperFile))
        if paper.get("file_name"):
            triples.append((uri, v.DOC.file_name, rdflib.Literal(paper["file_name"])))

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
            triples.append((uri, v.DOC.chunker_id, rdflib.Literal(chunk["chunker_id"])))

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
