"""Reverse-search application for extracted items.

A small hexagonal domain that lets researchers locate *where* (which paper,
which chunk) something is asserted, by:

- semantic (vector) search over ``phases-doc:ExtractedItem`` embeddings, and
- keyword (word-presence) search over the same items' text.

Both paths resolve every hit back to its source paper + chunk via SPARQL
(join-on-read against the knowledge graph), so no re-ingestion is required.

Layers
------
- ``models``     : technology-agnostic domain models (also used as API schemas).
- ``interfaces`` : ports the domain depends on (semantic index + knowledge graph).
- ``domain``     : ``SearchService`` — the business logic.
- ``adapters``   : secondary adapters (vector store / triple store) and the
                   primary adapter (FastAPI router).
- ``factory``    : wires the service from the running :class:`ABIModule` engine.
- ``frontend``   : the static single-page UI.
"""
