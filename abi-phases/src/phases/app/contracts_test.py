"""Run the generic port contracts against the in-memory fakes.

This proves the contract suite itself is correct; real adapter tests reuse the
same ``assert_*`` helpers against Qdrant / SPARQL-backed implementations.
"""

from __future__ import annotations

from phases.app.contracts import (
    assert_knowledge_graph_contract,
    assert_semantic_index_contract,
    canonical_items,
)
from phases.app.fakes import FakeKnowledgeGraph, FakeSemanticIndex


def test_fake_semantic_index_satisfies_contract():
    assert_semantic_index_contract(FakeSemanticIndex(canonical_items()))


def test_fake_knowledge_graph_satisfies_contract():
    assert_knowledge_graph_contract(FakeKnowledgeGraph(canonical_items()))
