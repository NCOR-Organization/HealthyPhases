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


@pytest.mark.skipif(
    os.environ.get("PUBMED_NETWORK_TESTS") != "1",
    reason="Opt-in public NCBI network check",
)
def test_live_uid_ranges_preserve_query_and_fetch_a_complete_leaf():
    from pubmed.application.pubmed_backfills import MAX_UID

    source = NcbiSource()
    query = {"query": "solitude", "start_date": "", "end_date": ""}
    total, ids = source.search_ids(query)
    bounded, _ = source.search_ids(query, 1, MAX_UID)
    assert total == bounded and ids
    count, leaf = source.search_ids(query, int(ids[0]), int(ids[0]))
    assert count == 1 and leaf == [ids[0]]
    assert source.summaries(leaf)[0]["pmid"] == leaf[0]
