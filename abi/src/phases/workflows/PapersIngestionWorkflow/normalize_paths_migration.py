"""One-shot migration: rewrite phases-doc:path literals to their normalized
absolute form (os.path.abspath) inside the papers named graph.

Background
----------
Earlier ingestion runs stored paths verbatim from `glob(...)`, which can produce
unnormalized values like ".../orchestrations/../papers/solitude/foo.pdf".
Going forward, PapersIngestionWorkflow normalizes paths at entry, but pre-existing
PDFPaperFile records still hold the old literal form, breaking exact-match SPARQL
filters.

This migration:
  1. Selects every (?paper, ?path) where ?paper a phases-doc:PDFPaperFile
     in the papers graph.
  2. For each row whose path differs from os.path.abspath(path), removes the old
     triple and inserts the normalized one.

It is idempotent: re-running on already-normalized data is a no-op.
"""

from __future__ import annotations

import os

import rdflib
from naas_abi_core import logger

from phases import ABIModule

PAPERS_GRAPH = rdflib.URIRef("http://ontology.naas.ai/graph/phases/papers")
PHASES_DOC_PATH = rdflib.URIRef(
    "http://purl.obolibrary.org/obo/phases/documents.owl#path"
)


def normalize_paper_paths() -> int:
    """Returns the number of triples rewritten."""
    module = ABIModule.get_instance()
    triple_store = module.engine.services.triple_store

    query = f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
SELECT ?paper ?path WHERE {{
    GRAPH <{PAPERS_GRAPH}> {{
        ?paper a phases-doc:PDFPaperFile ; phases-doc:path ?path .
    }}
}}"""

    rows = list(triple_store.query(query))
    logger.info(f"Inspecting {len(rows)} PDFPaperFile path literal(s)")

    rewrites = 0
    for paper, path in rows:
        old = str(path)
        new = os.path.abspath(old)
        if old == new:
            continue

        # rdflib literal datatype must match exactly to remove the triple.
        old_literal = (
            rdflib.Literal(old, datatype=path.datatype)
            if isinstance(path, rdflib.Literal) and path.datatype
            else rdflib.Literal(old)
        )
        new_literal = (
            rdflib.Literal(new, datatype=path.datatype)
            if isinstance(path, rdflib.Literal) and path.datatype
            else rdflib.Literal(new)
        )

        remove_g = rdflib.Graph()
        remove_g.add((paper, PHASES_DOC_PATH, old_literal))
        insert_g = rdflib.Graph()
        insert_g.add((paper, PHASES_DOC_PATH, new_literal))

        triple_store.remove(remove_g, graph_name=PAPERS_GRAPH)
        triple_store.insert(insert_g, graph_name=PAPERS_GRAPH)
        rewrites += 1
        logger.debug(f"Rewrote path for {paper}: {old} -> {new}")

    logger.info(f"normalize_paper_paths: rewrote {rewrites} triple(s)")
    return rewrites


if __name__ == "__main__":
    normalize_paper_paths()
