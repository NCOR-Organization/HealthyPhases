import hashlib

import pytest
import requests

from pubmed.adapters.secondary.pubmed_ncbi import CLOUD, NcbiSource
from pubmed.domain.pubmed_errors import AcquisitionError, FullTextUnavailable


class Response:
    def __init__(self, data=None, content=b"", status=200):
        self.data, self.content, self.status_code = data, content, status
        self.closed = False

    def json(self):
        return self.data

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def iter_content(self, chunk_size):
        yield self.content


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def versions(*names):
    content = '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated>'
    content += "".join(
        f"<CommonPrefixes><Prefix>{name}/</Prefix></CommonPrefixes>" for name in names
    )
    return Response(content=(content + "</ListBucketResult>").encode())


def test_download_discovers_versions_and_prefers_published_pdf():
    content = b"%PDF-1.7 downloaded"
    digest = hashlib.md5(content, usedforsecurity=False).hexdigest()
    session = Session(
        [
            versions("PMC123.2", "PMC123.3"),
            Response(
                {
                    "pdf_url": f"s3://pmc-oa-opendata/PMC123.2/paper.pdf?md5={digest}",
                    "is_manuscript": "no",
                    "license_code": "CC BY",
                }
            ),
            Response(
                {"pdf_url": CLOUD + "/PMC123.3/paper.pdf", "is_manuscript": "yes"}
            ),
            Response(content=content),
        ]
    )
    source = NcbiSource(session=session, sleep=lambda _: None)
    pdf, metadata = source.download("PMC123")
    assert pdf == content
    assert metadata["version"] == "PMC123.2"
    assert metadata["license"] == "CC BY"
    assert session.calls[0][1]["params"]["prefix"] == "PMC123."
    assert session.calls[-1][0] == CLOUD + f"/PMC123.2/paper.pdf?md5={digest}"


def test_metadata_without_pdf_is_unavailable():
    source = NcbiSource(
        session=Session([versions("PMC123.1"), Response({"text_url": "text"})]),
        sleep=lambda _: None,
    )
    with pytest.raises(FullTextUnavailable):
        source.download("PMC123")


def test_search_does_not_misassign_missing_summary_to_another_pmid():
    session = Session(
        [
            Response({"esearchresult": {"count": "2", "idlist": ["1", "2"]}}),
            Response({"result": {"2": {"title": "Second"}}}),
        ]
    )
    with pytest.raises(AcquisitionError, match="PMID 1"):
        NcbiSource(session=session, sleep=lambda _: None).search(
            {"query": "q", "sort": "relevance", "max_results": 2}
        )


@pytest.mark.parametrize(
    "dates, expected",
    [
        ({}, {}),
        ({"start_date": "", "end_date": ""}, {}),
        (
            {"start_date": "2026-01-01", "end_date": ""},
            {"mindate": "2026/01/01", "maxdate": "9999/12/31"},
        ),
        (
            {"start_date": "", "end_date": "2000-01-01"},
            {"mindate": "0001/01/01", "maxdate": "2000/01/01"},
        ),
        (
            {"start_date": "2025-01-01", "end_date": "2026-01-01"},
            {"mindate": "2025/01/01", "maxdate": "2026/01/01"},
        ),
    ],
)
def test_search_sends_both_date_bounds_or_neither(dates, expected):
    session = Session([Response({"esearchresult": {"count": "0", "idlist": []}})])
    NcbiSource(session=session, sleep=lambda _: None).search(
        {"query": "q", "sort": "relevance", "max_results": 1, **dates}
    )
    params = session.calls[0][1]["params"]
    assert {k: params[k] for k in ("mindate", "maxdate") if k in params} == expected
    assert params["datetype"] == "pdat"


def test_retry_is_bounded_and_server_error_is_not_treated_as_a_pdf():
    session = Session(
        [Response(status=503), Response(status=503), Response(status=503)]
    )
    with pytest.raises(AcquisitionError):
        NcbiSource(session=session, sleep=lambda _: None)._get(CLOUD)
    assert len(session.calls) == 3


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1/paper", "https://evil.test/paper", "s3://other/paper"]
)
def test_download_metadata_cannot_redirect_to_arbitrary_hosts(url):
    with pytest.raises(AcquisitionError):
        NcbiSource._pdf_url(url)


def test_rejects_corrupt_or_oversized_pdf():
    for limit, expected in [(100, "checksum"), (2, "size limit")]:
        source = NcbiSource(
            session=Session(
                [
                    versions("PMC123.1"),
                    Response({"pdf_url": CLOUD + "/p.pdf?md5=wrong"}),
                    Response(content=b"%PDF-1.7"),
                ]
            ),
            sleep=lambda _: None,
            max_pdf_bytes=limit,
        )
        with pytest.raises(AcquisitionError, match=expected):
            source.download("PMC123")


def test_backfill_range_keeps_expression_and_dates_without_preview_limit():
    session = Session(
        [Response({"esearchresult": {"count": "12000", "idlist": ["101"]}})]
    )
    count, ids = NcbiSource(session=session, sleep=lambda _: None).search_ids(
        {
            "query": "solitude OR loneliness",
            "start_date": "1900-01-01",
            "max_results": 1,
        },
        100,
        50000,
    )
    assert count == 12000 and ids == ["101"]
    params = session.calls[0][1]["params"]
    assert params["term"] == "(solitude OR loneliness) AND (100:50000[UID])"
    assert params["retmax"] == 200 and params["retstart"] == 0
    assert params["mindate"] == "1900/01/01" and params["maxdate"] == "9999/12/31"


@pytest.mark.parametrize(
    "result",
    [
        {"count": "2", "idlist": ["101"]},
        {"count": "2", "idlist": ["101", "101"]},
        {"count": "1", "idlist": ["999"]},
        {"count": "1", "idlist": ["bad"]},
        {"ERROR": "invalid expression"},
    ],
)
def test_backfill_cannot_treat_incomplete_or_invalid_ranges_as_success(result):
    source = NcbiSource(
        session=Session([Response({"esearchresult": result})]), sleep=lambda _: None
    )
    with pytest.raises(AcquisitionError):
        source.search_ids({"query": "solitude"}, 100, 200)
