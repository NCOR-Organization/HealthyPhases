"""What the app offers a user, without a web server in the way."""

import pytest

from phases_v2.app.service import PipelineAppService
from phases_v2.chunking.chunkers import WINDOW_512_128
from phases_v2.requests.fakes import FakeRequestStore
from phases_v2.requests.interfaces import PENDING


class _Rows:
    def __init__(self, results=None):
        self._results = results or {}

    def query(self, sql):
        for marker, rows in self._results.items():
            if marker in sql:
                return rows
        return []


class _Storage:
    def __init__(self, keys=None, raises=False):
        self._keys = keys or []
        self._raises = raises

    def list_objects(self, prefix):
        if self._raises:
            raise RuntimeError("no such prefix")
        return list(self._keys)


def _service(**kwargs):
    kwargs.setdefault("request_store", FakeRequestStore())
    return PipelineAppService(**kwargs)


def test_the_offered_prompts_models_and_chunkers_are_the_declared_ones():
    service = _service()

    assert service.prompts()
    assert service.models()
    assert {c["chunker_id"] for c in service.chunkers()} == {
        WINDOW_512_128.chunker_id
    }
    assert all("prompt_id" in p for p in service.prompts())
    assert all("model_id" in m for m in service.models())


def test_locations_come_from_object_storage():
    service = _service(object_storage=_Storage(["papers/", "archive/"]))

    assert service.locations() == ["archive", "papers"]


def test_a_missing_prefix_lists_nothing_rather_than_failing_the_page():
    service = _service(object_storage=_Storage(raises=True))

    assert service.locations("nope") == []


def test_submitting_records_a_pending_request():
    store = FakeRequestStore()
    service = _service(request_store=store)

    request = service.submit_run(
        locations=["papers"],
        chunker_id="w",
        prompt_id="p",
        model_id="m",
        requested_by="maxime",
    )

    assert request.status == PENDING
    assert store.get(request.request_id).requested_by == "maxime"


def test_submitting_without_a_required_input_is_refused_and_names_it():
    service = _service()

    with pytest.raises(ValueError, match="model_id"):
        service.submit_run(
            locations=["papers"], chunker_id="w", prompt_id="p", model_id=""
        )


def test_submitting_with_no_location_is_refused():
    service = _service()

    with pytest.raises(ValueError, match="locations"):
        service.submit_run(
            locations=[], chunker_id="w", prompt_id="p", model_id="m"
        )


def test_a_completed_request_reports_the_counts_of_its_run():
    store = FakeRequestStore()
    service = _service(
        request_store=store,
        rows=_Rows({"extraction_runs": [{"succeeded": 7, "failed": 1, "skipped": 2}]}),
    )
    request = service.submit_run(
        locations=["papers"], chunker_id="w", prompt_id="p", model_id="m"
    )

    assert service.request(request.request_id)["counts"] == {
        "succeeded": 7,
        "failed": 1,
        "skipped": 2,
    }


def test_a_request_with_no_run_yet_reports_no_counts():
    store = FakeRequestStore()
    service = _service(request_store=store, rows=_Rows())
    request = service.submit_run(
        locations=["papers"], chunker_id="w", prompt_id="p", model_id="m"
    )

    assert service.request(request.request_id)["counts"] is None


def test_choosing_a_different_chunker_warns_that_everything_re_runs():
    service = _service(rows=_Rows({"DISTINCT chunker_id": [{"chunker_id": "window_1_aaa"}]}))

    warning = service.chunker_warning("window_1_bbb")

    assert warning is not None
    assert "window_1_aaa" in warning
    assert "outstanding" in warning


def test_choosing_the_chunker_already_in_use_warns_about_nothing():
    service = _service(rows=_Rows({"DISTINCT chunker_id": [{"chunker_id": "window_1_aaa"}]}))

    assert service.chunker_warning("window_1_aaa") is None


def test_an_empty_corpus_warns_about_nothing():
    service = _service(rows=_Rows({"DISTINCT chunker_id": []}))

    assert service.chunker_warning("window_1_aaa") is None
