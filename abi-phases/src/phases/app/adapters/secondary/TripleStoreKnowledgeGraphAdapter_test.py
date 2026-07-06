"""Validate the real SPARQL adapter against an in-memory rdflib dataset.

Seeds the two named graphs (``papers`` + ``extractions``) with the exact
predicate shapes the ingestion/extraction workflows persist, then runs the
generic knowledge-graph port contract. This exercises the cross-graph join,
the OPTIONAL provenance block, and the positional row unpacking for real.
"""

from __future__ import annotations

import rdflib

from phases.app.adapters.secondary.TripleStoreKnowledgeGraphAdapter import (
    EXTRACTIONS_GRAPH,
    PAPERS_GRAPH,
    PHASES_DOC,
    TripleStoreKnowledgeGraphAdapter,
)
from phases.app.contracts import assert_knowledge_graph_contract, canonical_items

DOC = rdflib.Namespace(PHASES_DOC)


class _RdflibTripleStore:
    """Minimal stand-in exposing the ``.query`` method the adapter uses."""

    def __init__(self, dataset: rdflib.Dataset):
        self._dataset = dataset

    def query(self, query: str):
        return self._dataset.query(query)


def _seed_dataset() -> rdflib.Dataset:
    ds = rdflib.Dataset()
    papers = ds.graph(rdflib.URIRef(PAPERS_GRAPH))
    extractions = ds.graph(rdflib.URIRef(EXTRACTIONS_GRAPH))

    for n, item in enumerate(canonical_items()):
        loc = item.location
        chunk = rdflib.URIRef(f"urn:test:chunk:{loc.chunk_id}")
        paper = rdflib.URIRef(f"urn:test:paper:{n}")
        extraction = rdflib.URIRef(f"urn:test:extraction:{loc.pipeline}")
        ext_item = rdflib.URIRef(f"urn:test:item:{item.extracted_item_id}")

        # papers graph
        papers.add((chunk, rdflib.RDF.type, DOC.Chunk))
        papers.add((chunk, DOC.chunk_id, rdflib.Literal(loc.chunk_id)))
        papers.add((chunk, DOC.chunk_number, rdflib.Literal(loc.chunk_number)))
        papers.add((chunk, DOC.text, rdflib.Literal(loc.chunk_text)))
        papers.add((chunk, DOC.chunk_of, paper))
        papers.add((paper, rdflib.RDF.type, DOC.PDFPaperFile))
        papers.add((paper, DOC.path, rdflib.Literal(loc.paper_path)))

        # extractions graph
        extractions.add((extraction, rdflib.RDF.type, DOC.Extraction))
        extractions.add((extraction, DOC.pipeline_name, rdflib.Literal(loc.pipeline)))
        extractions.add((extraction, DOC.model_name, rdflib.Literal(loc.model)))
        extractions.add((ext_item, rdflib.RDF.type, DOC.ExtractedItem))
        extractions.add(
            (ext_item, DOC.extracted_item_id, rdflib.Literal(item.extracted_item_id))
        )
        extractions.add((ext_item, DOC.extracted_text, rdflib.Literal(item.text)))
        extractions.add((ext_item, DOC.extracted_by, extraction))
        extractions.add((ext_item, DOC.extracted_from_chunk, chunk))

    return ds


def _adapter() -> TripleStoreKnowledgeGraphAdapter:
    store = _RdflibTripleStore(_seed_dataset())
    return TripleStoreKnowledgeGraphAdapter(store)  # type: ignore[arg-type]


def test_real_sparql_adapter_satisfies_contract():
    assert_knowledge_graph_contract(_adapter())


def test_resolve_locations_full_provenance():
    locs = _adapter().resolve_locations(["item-effects"])
    loc = locs["item-effects"]
    assert loc.pipeline == "effects"
    assert loc.model == "gpt-5-mini"
    assert loc.chunk_number == 1
    assert loc.chunk_id == "chunk-1"
    assert loc.paper_name == "a.pdf"
    assert "solitude reduces stress" in loc.chunk_text.lower()


def test_keyword_search_orders_and_limits():
    hits = _adapter().keyword_search(["solitude"], pipelines=None, limit=1)
    assert len(hits) == 1
