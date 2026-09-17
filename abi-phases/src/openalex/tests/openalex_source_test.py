from unittest.mock import Mock

import pytest
import requests

from openalex.adapters.secondary.openalex_source import OpenalexSource
from openalex.contracts.openalex_validation import validate
from openalex.domain.openalex_errors import OpenalexUnavailable
from openalex.domain.openalex_matching import match, normalize_doi
from openalex.domain.openalex_work import normalize_work
from openalex.tests.openalex_service_test import raw


def response(status, payload=None, **headers):
    return Mock(status_code=status, headers=headers, json=Mock(return_value=payload))


def test_exact_matching_never_accepts_conflicts_or_unconfirmed_identity():
    paper = {"pmid": "123", "doi": "https://doi.org/10.1234/ABC"}
    assert normalize_doi(paper["doi"]) == "10.1234/abc"
    assert match(paper, [raw("123", "10.1234/abc")])[0] == "enriched"
    assert (
        match(paper, [raw("123", "10.1234/abc"), raw("123", "10.1234/abc", "W999")])[0]
        == "ambiguous"
    )
    assert match(paper, [raw("456", "10.1234/abc")])[0] == "ambiguous"
    assert match(paper, [{"id": "W123"}])[0] == "ambiguous"
    assert match(paper, [])[0] == "no_match"
    assert match(paper, [raw("123", "10.1234/wrong")])[0] == "ambiguous"


def test_rate_limits_timeout_retry_budget_and_credentials_are_not_in_url():
    session, sleeper, budget = Mock(), Mock(), Mock()
    session.get.side_effect = [
        requests.Timeout("secret URL"),
        response(429, **{"Retry-After": "500"}),
        response(200, raw("123")),
    ]
    source = OpenalexSource("private-key", session=session, sleeper=sleeper)
    assert source.lookup("pmid:123", budget)["id"].endswith("W123")
    assert budget.call_count == 3
    assert 30 in [call.args[0] for call in sleeper.call_args_list]
    for call in session.get.call_args_list:
        assert call.args[0] == "https://api.openalex.org/works/pmid:123"
        assert call.kwargs["headers"]["Authorization"] == "Bearer private-key"
        assert call.kwargs["timeout"] == 30 and not call.kwargs["allow_redirects"]


def test_not_found_auth_errors_invalid_records_and_foreign_redirects():
    session = Mock()
    source = OpenalexSource("secret", session=session, sleeper=lambda _: None)
    budget = Mock()
    session.get.return_value = response(404)
    assert source.lookup("pmid:123", budget) is None
    session.get.return_value = response(401)
    with pytest.raises(OpenalexUnavailable, match="credentials"):
        source.lookup("pmid:123", budget)
    session.get.return_value = response(200, {"id": "broken"})
    with pytest.raises(OpenalexUnavailable, match="invalid"):
        source.lookup("pmid:123", budget)
    session.get.return_value = response(301, Location="https://evil.example/steal")
    before = session.get.call_count
    with pytest.raises(OpenalexUnavailable, match="redirect"):
        source.lookup("pmid:123", budget)
    assert session.get.call_count == before + 1


def test_merged_work_redirect_and_missing_optional_metadata():
    session = Mock()
    session.get.side_effect = [
        response(301, Location="https://api.openalex.org/works/W999"),
        response(200, raw("123", work="W999")),
    ]
    source = OpenalexSource(session=session, sleeper=lambda _: None)
    budget = Mock()
    result = source.lookup("pmid:123", budget)
    assert budget.call_count == 2
    normalized = validate("WorkRecord", normalize_work(result))
    assert normalized["work_id"] == "W999"
    assert normalized["locations"] == [] and normalized["publication_year"] == 0
    with pytest.raises(ValueError):
        validate("EnrichQuery", {"query_id": "invalid"})
    with pytest.raises(ValueError):
        validate(
            "PaperEnrichment",
            {
                "pmid": "123",
                "status": "enriched",
                "citation_count": -1,
                "contract_version": 1,
            },
        )
