"""The RDF vocabulary this module projects into.

The class and property URIs are **the same ones ``phases`` uses** — the
``documents.owl#`` namespace — even though the two modules write to different
named graphs and keep separate copies of the TTL. Graphs are separate so
neither can disturb the other; vocabulary is shared so a Composer query written
against v1's shapes works against v2's graphs by changing only the GRAPH clause.

The TTL files beside this module are its own copy, so the module stays
self-sufficient. Unlike v1 nothing is generated at import time: these are the
handful of terms the projector actually emits, and a test checks each one
against the TTL rather than trusting this list.
"""

from __future__ import annotations

import rdflib

# Shared with `phases`. Changing this would fork the vocabulary.
DOC = rdflib.Namespace("http://purl.obolibrary.org/obo/phases/documents.owl#")

# This module's own graphs, distinct from v1's `phases/papers` and
# `phases/extractions`.
GRAPH_BASE = "http://ontology.naas.ai/graph/phases/v2"
PAPERS_GRAPH = rdflib.URIRef(f"{GRAPH_BASE}/papers")
EXTRACTIONS_GRAPH = rdflib.URIRef(f"{GRAPH_BASE}/extractions")

# Instance URIs. The local name is the content-addressed id, which is what
# makes re-projecting the same row produce byte-identical triples.
URN = "urn:phases:v2"


def paper_uri(paper_id: str) -> rdflib.URIRef:
    return rdflib.URIRef(f"{URN}:paper:{paper_id}")


def chunk_uri(chunk_id: str) -> rdflib.URIRef:
    return rdflib.URIRef(f"{URN}:chunk:{chunk_id}")


def extraction_uri(extraction_id: str) -> rdflib.URIRef:
    return rdflib.URIRef(f"{URN}:extraction:{extraction_id}")


def item_uri(item_id: str) -> rdflib.URIRef:
    return rdflib.URIRef(f"{URN}:item:{item_id}")
