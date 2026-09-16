"""Opt-in, read-only smoke check; creates no dataset or object-storage records."""

import os

import pytest

from pubmed.adapters.secondary.pubmed_ncbi import NcbiSource


@pytest.mark.skipif(
    os.environ.get("PUBMED_NETWORK_TESTS") != "1",
    reason="Opt-in public NCBI network check",
)
def test_live_search_and_pmc_cloud_pdf():
    source = NcbiSource()
    total, papers = source.search(
        {"query": "solitude", "sort": "relevance", "max_results": 1}
    )
    assert total > 0 and len(papers) == 1
    content, metadata = source.download("PMC10009416")
    assert content.startswith(b"%PDF-")
    assert metadata["source_url"].startswith(
        "https://pmc-oa-opendata.s3.amazonaws.com/"
    )
