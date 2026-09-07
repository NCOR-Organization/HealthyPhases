"""The triple-store sink.

Exists because the in-memory fake could not catch this: the fake takes a graph
uri as a string, while the real service requires a separate ``graph_name``
argument. Omitting it raised only against a live store.
"""

import rdflib

from phases_v2.ontologies import vocabulary as v
from phases_v2.projection.adapters.secondary.TripleStoreSink import TripleStoreSink


class _StubTripleStore:
    def __init__(self):
        self.calls = []

    def insert(self, triples, graph_name):
        self.calls.append((triples, graph_name))


def test_the_graph_name_is_passed_to_the_store():
    store = _StubTripleStore()
    subject = rdflib.URIRef("urn:phases:v2:item:x")

    TripleStoreSink(store).insert(
        str(v.EXTRACTIONS_GRAPH), [(subject, v.DOC.extracted_text, rdflib.Literal("x"))]
    )

    [(graph, graph_name)] = store.calls
    assert graph_name == v.EXTRACTIONS_GRAPH
    assert len(graph) == 1


def test_the_graph_carries_the_name_as_its_identifier_too():
    store = _StubTripleStore()

    TripleStoreSink(store).insert(
        str(v.PAPERS_GRAPH),
        [(rdflib.URIRef("urn:x"), rdflib.RDF.type, v.DOC.PDFPaperFile)],
    )

    [(graph, _name)] = store.calls
    assert graph.identifier == v.PAPERS_GRAPH


def test_every_triple_reaches_the_store():
    store = _StubTripleStore()
    triples = [
        (rdflib.URIRef(f"urn:x:{i}"), v.DOC.extracted_text, rdflib.Literal(str(i)))
        for i in range(5)
    ]

    TripleStoreSink(store).insert(str(v.EXTRACTIONS_GRAPH), triples)

    [(graph, _name)] = store.calls
    assert set(graph) == set(triples)
