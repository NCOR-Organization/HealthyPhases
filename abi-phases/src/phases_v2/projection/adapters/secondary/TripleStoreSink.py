"""The engine's triple store, as the projectors' :class:`TripleSink`."""

from __future__ import annotations

import rdflib


class TripleStoreSink:
    def __init__(self, triple_store):
        self._triple_store = triple_store

    def insert(self, graph_uri: str, triples: list[tuple]) -> None:
        name = rdflib.URIRef(graph_uri)
        graph = rdflib.Graph(identifier=name)
        for triple in triples:
            graph.add(triple)
        self._triple_store.insert(graph, graph_name=name)
