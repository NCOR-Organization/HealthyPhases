"""The Dagster definitions and the sensor's request mapping.

The mapping is tested as a pure function: it is the part that carries the
exactly-once guarantee, and it should not need a running Dagster to check.
"""

import sys
from datetime import UTC, datetime
from importlib import import_module
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import dagster as dg

from phases_v2.orchestrations.PhasesV2Orchestration import (
    PhasesV2Orchestration,
    build_run_requests,
    full_pipeline_job,
)
from phases_v2.requests.interfaces import PENDING, RunRequest


def _request(request_id="req-1"):
    return RunRequest(
        request_id=request_id,
        status=PENDING,
        locations=["papers"],
        chunker_id="window_1_abc",
        prompt_ids=["claims_abc", "other_prompt"],
        model_id="openai/gpt-4.1-mini",
        requested_at=datetime.now(UTC),
    )


def test_engine_access_reuses_the_bootstrapped_instance(monkeypatch):
    from phases_v2.orchestrations.PhasesV2Orchestration import _engine

    entrypoint = ModuleType("naas_abi_core.apps.dagster.dagster")
    entrypoint.engine = object()
    monkeypatch.setitem(sys.modules, entrypoint.__name__, entrypoint)
    constructor = Mock(side_effect=AssertionError("Engine must not be rebuilt"))
    monkeypatch.setattr(
        import_module("naas_abi_core.engine.Engine"), "Engine", constructor
    )

    assert _engine() is entrypoint.engine
    assert _engine() is entrypoint.engine
    constructor.assert_not_called()


def test_prompts_and_sensor_ticks_share_the_bootstrapped_engine(monkeypatch):
    from phases_v2.orchestrations.PhasesV2Orchestration import (
        RunConfig,
        run_extraction_op,
        run_request_sensor,
    )

    entrypoint = ModuleType("naas_abi_core.apps.dagster.dagster")
    available = Mock(return_value=False)
    entrypoint.engine = SimpleNamespace(
        services=SimpleNamespace(dataset_available=available),
        modules={
            "phases_v2": SimpleNamespace(
                configuration=SimpleNamespace(extraction_workers=7)
            )
        },
    )
    monkeypatch.setitem(sys.modules, entrypoint.__name__, entrypoint)
    extract = Mock(return_value=SimpleNamespace(succeeded=1, failed=0, skipped=0))
    monkeypatch.setattr("phases_v2.extraction.factory.extract", extract)

    with dg.build_op_context() as context:
        totals = run_extraction_op(
            context, RunConfig(prompt_ids=["first", "second"]), after={}
        )
    with dg.build_sensor_context() as context:
        assert isinstance(run_request_sensor(context), dg.SkipReason)
        assert isinstance(run_request_sensor(context), dg.SkipReason)

    assert totals == {"succeeded": 2, "failed": 0, "skipped": 0}
    assert [call.args[0] for call in extract.call_args_list] == [
        entrypoint.engine,
        entrypoint.engine,
    ]
    assert [call.kwargs["prompt_id"] for call in extract.call_args_list] == [
        "first",
        "second",
    ]
    assert all(call.kwargs["workers"] == 7 for call in extract.call_args_list)
    assert available.call_count == 2


def test_the_definitions_expose_every_stage_and_the_pipeline():
    definitions = PhasesV2Orchestration.New().definitions

    names = {job.name for job in definitions.jobs}
    assert names == {
        "phases_v2_ingest_papers",
        "phases_v2_chunk_papers",
        "phases_v2_run_extraction",
        "phases_v2_project_graph",
        "phases_v2_project_vectors",
        "phases_v2_refresh_vector_metadata",
        "phases_v2_full_pipeline",
    }


def test_the_sensor_is_registered_against_the_full_pipeline():
    definitions = PhasesV2Orchestration.New().definitions

    names = {sensor.name for sensor in definitions.sensors}
    assert "phases_v2_run_request_sensor" in names


def test_the_run_key_is_the_request_id():
    # This is the exactly-once guarantee: Dagster will not start a second run
    # for a run key it has already seen.
    [run_request] = build_run_requests([_request("req-1")])

    assert run_request.run_key == "req-1"


def test_observing_the_same_request_twice_yields_the_same_run_key():
    request = _request("req-1")

    first = build_run_requests([request])[0]
    second = build_run_requests([request])[0]

    assert first.run_key == second.run_key


def test_several_pending_requests_each_get_their_own_run():
    requests = build_run_requests([_request("a"), _request("b")])

    assert [r.run_key for r in requests] == ["a", "b"]


def test_the_selected_inputs_reach_every_op_that_needs_them():
    [run_request] = build_run_requests([_request()])

    ops = run_request.run_config["ops"]
    for op in ("ingest_papers_op", "chunk_papers_op", "run_extraction_op"):
        assert ops[op]["config"]["locations"] == ["papers"]
        assert ops[op]["config"]["model_id"] == "openai/gpt-4.1-mini"
        assert ops[op]["config"]["prompt_ids"] == ["claims_abc", "other_prompt"]
        assert ops[op]["config"]["chunker_id"] == "window_1_abc"


def test_the_request_id_is_carried_so_the_job_can_close_it_out():
    [run_request] = build_run_requests([_request("req-9")])

    ops = run_request.run_config["ops"]
    assert ops["claim_request_op"]["config"]["request_id"] == "req-9"
    assert ops["complete_request_op"]["config"]["request_id"] == "req-9"


def test_no_pending_requests_produce_no_runs():
    assert build_run_requests([]) == []


def test_extraction_and_the_pipeline_share_a_concurrency_key():
    # Two runs over the same scope would both find the work outstanding and
    # both pay a model for it.
    assert full_pipeline_job.tags["dagster/concurrency_key"] == "phases_v2_extraction"


def test_the_run_config_is_accepted_by_the_job():
    # A config the job rejects would fail at launch, after the sensor has
    # already consumed the run key.
    [run_request] = build_run_requests([_request()])

    result = dg.validate_run_config(full_pipeline_job, run_request.run_config)

    # Validate without starting the engine or contacting production services.
    assert result is not None


def test_the_request_id_travels_as_a_run_tag_too():
    from phases_v2.orchestrations.PhasesV2Orchestration import REQUEST_TAG

    [run_request] = build_run_requests([_request("req-7")])

    assert run_request.tags[REQUEST_TAG] == "req-7"


def test_a_failed_run_can_be_traced_back_to_its_request():
    from phases_v2.orchestrations.PhasesV2Orchestration import (
        REQUEST_TAG,
        request_id_of,
    )

    assert request_id_of({REQUEST_TAG: "req-7"}) == "req-7"


def test_a_run_started_by_hand_has_no_request_to_fail():
    from phases_v2.orchestrations.PhasesV2Orchestration import request_id_of

    assert request_id_of({}) is None
    assert request_id_of({"other": "tag"}) is None


def test_the_failure_sensor_is_registered():
    definitions = PhasesV2Orchestration.New().definitions

    assert {s.name for s in definitions.sensors} == {
        "phases_v2_run_request_sensor",
        "phases_v2_run_failure_sensor",
    }


def test_each_prompt_of_a_request_gets_its_own_extraction_run_id():
    # `extraction_runs.run_id` is the primary key, so the request id alone
    # would make several prompts collide onto one row.
    from phases_v2.orchestrations.PhasesV2Orchestration import extraction_run_id

    first = extraction_run_id("req-1", "solitude_what_aaa")
    second = extraction_run_id("req-1", "solitude_causes_bbb")

    assert first != second
    assert first.startswith("req-1")


def test_the_run_carries_every_selected_prompt():
    [run_request] = build_run_requests([_request()])

    config = run_request.run_config["ops"]["run_extraction_op"]["config"]
    assert config["prompt_ids"] == ["claims_abc", "other_prompt"]


def test_the_sensors_are_running_by_default():
    # Dagster leaves sensors stopped unless told otherwise. A stopped request
    # sensor makes the app look broken: the request is recorded, the UI says
    # pending, and nothing ever picks it up.
    import dagster as dg

    definitions = PhasesV2Orchestration.New().definitions

    for sensor in definitions.sensors:
        assert sensor.default_status == dg.DefaultSensorStatus.RUNNING, sensor.name


def test_the_pipeline_stages_run_in_order_not_in_parallel():
    # Dagster infers concurrency from the dependency graph. Without an explicit
    # chain it ran all five stages at once: chunking found no papers because
    # ingestion had not finished, and five processes contended for one SQLite
    # catalog.
    deps = full_pipeline_job.graph.dependencies

    def upstream(node_name):
        for node, inputs in deps.items():
            if node.name == node_name:
                return {dep.node for dep in inputs.values()}
        return set()

    assert upstream("ingest_papers_op") == {"claim_request_op"}
    assert upstream("chunk_papers_op") == {"ingest_papers_op"}
    assert upstream("run_extraction_op") == {"chunk_papers_op"}
    assert upstream("project_graph_op") == {"run_extraction_op"}
    assert upstream("project_vectors_op") == {"project_graph_op"}
    assert upstream("complete_request_op") == {"project_vectors_op"}


def test_no_stage_is_left_without_an_upstream_dependency():
    # A stage with no upstream would run immediately, in parallel with the rest.
    graph = full_pipeline_job.graph
    nodes = {n.name for n in graph.nodes}
    with_upstream = {node.name for node, inputs in graph.dependencies.items() if inputs}

    assert nodes - with_upstream == {"claim_request_op"}


def test_requested_pipeline_carries_empty_scope_without_falling_back_to_corpus(
    monkeypatch,
):
    from phases_v2.orchestrations.PhasesV2Orchestration import (
        RunConfig,
        chunk_papers_op,
        run_extraction_op,
    )

    module = import_module("phases_v2.orchestrations.PhasesV2Orchestration")
    engine = SimpleNamespace(
        modules={
            "phases_v2": SimpleNamespace(
                configuration=SimpleNamespace(extraction_workers=1)
            )
        }
    )
    monkeypatch.setattr(module, "_engine", lambda: engine)
    chunk = Mock(return_value=SimpleNamespace(papers_chunked=0, chunks_written=0))
    extract = Mock(return_value=SimpleNamespace(succeeded=0, failed=0, skipped=0))
    monkeypatch.setattr("phases_v2.chunking.factory.chunk_corpus", chunk)
    monkeypatch.setattr("phases_v2.extraction.factory.extract", extract)
    config = RunConfig(request_id="requested", prompt_ids=["custom"])
    with dg.build_op_context() as context:
        chunked = chunk_papers_op(context, config, after={"paper_ids": []})
        run_extraction_op(context, config, after=chunked)
    assert chunk.call_args.kwargs["paper_ids"] == []
    assert extract.call_args.kwargs["paper_ids"] == []


def test_requested_pipeline_refuses_missing_document_scope(monkeypatch):
    import pytest

    from phases_v2.orchestrations.PhasesV2Orchestration import (
        RunConfig,
        chunk_papers_op,
    )

    chunk = Mock()
    monkeypatch.setattr("phases_v2.chunking.factory.chunk_corpus", chunk)
    with dg.build_op_context() as context, pytest.raises(ValueError, match="scope"):
        chunk_papers_op(context, RunConfig(request_id="requested"), after={})
    chunk.assert_not_called()
