"""The fake reader classifies stored extractions as the dataset adapter does."""

from phases_v2.coverage.fakes import FakeCoverageReader, _state
from phases_v2.coverage.interfaces import (
    FAILED_CALL,
    INVALID_ANSWER,
    NOT_RUN,
    SUCCEEDED,
    CoverageReader,
)


def test_a_failed_extraction_with_an_answer_stored_is_an_invalid_answer():
    assert _state(None) == NOT_RUN
    assert _state({"status": "succeeded"}) == SUCCEEDED
    assert _state({"status": "failed", "raw_response": None}) == FAILED_CALL
    assert _state({"status": "failed", "raw_response": "  "}) == FAILED_CALL
    assert _state({"status": "failed", "raw_response": "{}"}) == INVALID_ANSWER


def test_the_fake_offers_exactly_what_the_port_declares():
    declared = {n for n in vars(CoverageReader) if not n.startswith("_")}
    offered = {
        n
        for n in vars(FakeCoverageReader)
        if not n.startswith("_") and callable(getattr(FakeCoverageReader, n))
    }

    assert declared <= offered
    assert not {n for n in offered if "write" in n or n.startswith("save_")}
