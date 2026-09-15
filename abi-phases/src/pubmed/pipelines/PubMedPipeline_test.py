from pubmed.pipelines.PubMedPipeline import (
    PubMedPipeline,
    PubMedPipelineConfiguration,
    PubMedPipelineParameters,
)


def test_pubmed_pipeline(monkeypatch):
    from types import SimpleNamespace

    from rdflib import Graph, URIRef

    from pubmed.integrations.PubMedAPI import PubMedIntegration

    graph = Graph()
    graph.add((URIRef("urn:paper"), URIRef("urn:kind"), URIRef("urn:pdf")))
    monkeypatch.setattr(
        PubMedIntegration,
        "search_date_range",
        lambda *args, **kwargs: [SimpleNamespace(rdf=lambda: graph)],
    )
    pipeline = PubMedPipeline(PubMedPipelineConfiguration())
    results = pipeline.run(
        PubMedPipelineParameters(query="rheumatoid arthritis", start_date="2025-01-01")
    )
    assert len(results) > 0
