"""The vocabulary must stay the one v1 uses, and the graphs must not."""

import pathlib

import rdflib

from phases_v2.ontologies import vocabulary as v

TTL_DIR = pathlib.Path(v.__file__).parent


def test_the_namespace_is_the_one_v1_writes():
    # Hard-coded rather than imported from `phases`: this module must not
    # depend on v1's import path, but it must not drift from its vocabulary.
    assert str(v.DOC) == "http://purl.obolibrary.org/obo/phases/documents.owl#"


def test_the_graphs_are_this_modules_own():
    assert "phases/v2/" in str(v.PAPERS_GRAPH)
    assert "phases/v2/" in str(v.EXTRACTIONS_GRAPH)
    assert v.PAPERS_GRAPH != v.EXTRACTIONS_GRAPH


def test_the_graphs_are_not_the_ones_v1_writes():
    for graph in (v.PAPERS_GRAPH, v.EXTRACTIONS_GRAPH):
        assert str(graph) != "http://ontology.naas.ai/graph/phases/papers"
        assert str(graph) != "http://ontology.naas.ai/graph/phases/extractions"


def test_the_module_carries_its_own_ontology_files():
    assert (TTL_DIR / "documents.ttl").is_file()
    assert (TTL_DIR / "bfo_core.ttl").is_file()


def test_the_copied_ontology_declares_the_namespace_it_is_used_under():
    text = (TTL_DIR / "documents.ttl").read_text()

    assert "phases/documents.owl" in text


def test_the_copied_ontology_parses():
    graph = rdflib.Graph()
    graph.parse(TTL_DIR / "documents.ttl", format="turtle")

    assert len(graph) > 0


def test_instance_uris_are_stable_and_distinct_per_kind():
    # The local name is the content-addressed id, so re-projecting a row emits
    # the same URI; the kind prefix keeps a paper and a chunk sharing an id
    # from colliding.
    assert v.paper_uri("x") == v.paper_uri("x")
    assert (
        len(
            {
                v.paper_uri("x"),
                v.chunk_uri("x"),
                v.extraction_uri("x"),
                v.item_uri("x"),
            }
        )
        == 4
    )
