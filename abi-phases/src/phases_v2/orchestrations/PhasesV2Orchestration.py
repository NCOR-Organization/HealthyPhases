"""Dagster jobs for the pipeline, and the sensor that picks up run requests.

Each stage is its own job so it can be run alone, plus a ``full_pipeline`` that
chains them in order. Every stage is idempotent, so re-running any of them —
alone or as part of the whole chain — is safe.

The sensor is what connects the app to the orchestrator. The app records a
pending ``run_requests`` row and stops; the sensor turns each pending row into
a ``RunRequest`` keyed on the request id. Dagster will not start a second run
for a run key it has already seen, so the sensor observing the same row twice
before the run appears cannot double-launch it — which is exactly why the
request id is the run key.

Note what the sensor does *not* do: it never marks a request running. The job
does that, so a sensor that crashes mid-evaluation cannot strand a request in a
state no run is working on.
"""

import dagster as dg
from naas_abi_core.orchestrations.DagsterOrchestration import DagsterOrchestration
from typing import Optional

SENSOR_INTERVAL_SECONDS = 30
REQUEST_TAG = "phases_v2/request_id"


def _engine():
    """The loaded engine. Imported late so module import stays cheap."""
    from naas_abi_core.engine.Engine import Engine

    engine = Engine()
    engine.load()
    return engine


# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------


class RunConfig(dg.Config):
    """What a run is scoped to. Every field has a usable default."""

    locations: list[str] = ["papers"]
    chunker_id: str = ""
    prompt_id: str = ""
    model_id: str = ""
    request_id: str = ""
    max_chunks: Optional[int] = None


def _chunker(chunker_id: str):
    from phases_v2.chunking.chunkers import WINDOW_512_128
    from phases_v2.chunking.factory import resolve_chunker

    return resolve_chunker(chunker_id) if chunker_id else WINDOW_512_128


@dg.op
def ingest_papers_op(context: dg.OpExecutionContext, config: RunConfig) -> dict:
    from phases_v2.papers.factory import ingest_papers

    report = ingest_papers(_engine(), config.locations)
    context.log.info(
        f"ingested={report.ingested} skipped={report.skipped} failed={report.failed}"
    )
    return {"ingested": report.ingested, "skipped": report.skipped}


@dg.op
def chunk_papers_op(context: dg.OpExecutionContext, config: RunConfig) -> dict:
    from phases_v2.chunking.factory import chunk_corpus

    report = chunk_corpus(_engine(), chunker=_chunker(config.chunker_id))
    context.log.info(
        f"papers_chunked={report.papers_chunked} chunks={report.chunks_written}"
    )
    return {"chunks_written": report.chunks_written}


@dg.op
def run_extraction_op(context: dg.OpExecutionContext, config: RunConfig) -> dict:
    from phases_v2.extraction.factory import extract

    report = extract(
        _engine(),
        model_id=config.model_id,
        prompt_id=config.prompt_id,
        chunker=_chunker(config.chunker_id),
        max_chunks=config.max_chunks,
        # Use the request id so its counts can be found by that id later.
        run_id=config.request_id or None,
    )
    context.log.info(
        f"succeeded={report.succeeded} failed={report.failed} "
        f"skipped={report.skipped}"
    )
    return {
        "succeeded": report.succeeded,
        "failed": report.failed,
        "skipped": report.skipped,
    }


@dg.op
def project_graph_op(context: dg.OpExecutionContext) -> dict:
    from phases_v2.projection.factory import project_to_graph

    report = project_to_graph(_engine())
    context.log.info(f"projected={report.projected}")
    return {"projected": report.projected}


@dg.op
def project_vectors_op(context: dg.OpExecutionContext) -> dict:
    from phases_v2.projection.factory import project_to_vectors

    report = project_to_vectors(_engine())
    context.log.info(f"embedded={report.projected}")
    return {"embedded": report.projected}


@dg.job(name="phases_v2_ingest_papers")
def ingest_papers_job():
    ingest_papers_op()


@dg.job(name="phases_v2_chunk_papers")
def chunk_papers_job():
    chunk_papers_op()


@dg.job(
    name="phases_v2_run_extraction",
    # One extraction at a time per scope: concurrent runs over the same
    # chunk x model x prompt would both find the work outstanding and both
    # pay for it.
    tags={"dagster/concurrency_key": "phases_v2_extraction"},
)
def run_extraction_job():
    run_extraction_op()


@dg.job(name="phases_v2_project_graph")
def project_graph_job():
    project_graph_op()


@dg.job(name="phases_v2_project_vectors")
def project_vectors_job():
    project_vectors_op()


@dg.op
def complete_request_op(
    context: dg.OpExecutionContext,
    config: RunConfig,
    _ingested: dict,
    _chunked: dict,
    _extracted: dict,
    _graph: dict,
    _vectors: dict,
) -> None:
    """Close out the request this run was started for, if there was one."""
    if not config.request_id:
        return
    from phases_v2.requests.domain import finish
    from phases_v2.requests.factory import request_store

    finish(request_store(_engine()), config.request_id)
    context.log.info(f"request {config.request_id} completed")


@dg.op
def claim_request_op(context: dg.OpExecutionContext, config: RunConfig) -> None:
    """Mark the request running. The job owns this, not the sensor."""
    if not config.request_id:
        return
    from phases_v2.requests.domain import start
    from phases_v2.requests.factory import request_store

    start(request_store(_engine()), config.request_id, run_id=context.run_id)


@dg.job(
    name="phases_v2_full_pipeline",
    tags={"dagster/concurrency_key": "phases_v2_extraction"},
)
def full_pipeline_job():
    claim_request_op()
    complete_request_op(
        ingest_papers_op(),
        chunk_papers_op(),
        run_extraction_op(),
        project_graph_op(),
        project_vectors_op(),
    )


# --------------------------------------------------------------------------
# The sensor
# --------------------------------------------------------------------------


def build_run_requests(pending) -> list[dg.RunRequest]:
    """Turn pending request rows into Dagster run requests.

    Pure, so the mapping can be tested without an engine or a Dagster context.
    The run key is the request id: that is what makes a request produce exactly
    one run however often it is observed while pending.
    """
    return [
        dg.RunRequest(
            run_key=request.request_id,
            # Also a tag: a failed run is traced back through this without
            # having to parse its config.
            tags={REQUEST_TAG: request.request_id},
            run_config={
                "ops": {
                    op: {
                        "config": {
                            "locations": list(request.locations),
                            "chunker_id": request.chunker_id,
                            "prompt_id": request.prompt_id,
                            "model_id": request.model_id,
                            "request_id": request.request_id,
                        }
                    }
                    for op in (
                        "claim_request_op",
                        "ingest_papers_op",
                        "chunk_papers_op",
                        "run_extraction_op",
                        "complete_request_op",
                    )
                }
            },
        )
        for request in pending
    ]


@dg.sensor(
    name="phases_v2_run_request_sensor",
    job=full_pipeline_job,
    minimum_interval_seconds=SENSOR_INTERVAL_SECONDS,
)
def run_request_sensor(context: dg.SensorEvaluationContext):
    from phases_v2.requests.factory import request_store

    engine = _engine()
    if not engine.services.dataset_available():
        return dg.SkipReason("no dataset service is configured")

    pending = request_store(engine).pending()
    if not pending:
        return dg.SkipReason("no pending run requests")

    context.log.info(f"{len(pending)} pending run request(s)")
    return build_run_requests(pending)


def request_id_of(tags: dict) -> str | None:
    """The request a run was started for, if any."""
    return tags.get(REQUEST_TAG) or None


@dg.run_failure_sensor(
    name="phases_v2_run_failure_sensor",
    monitored_jobs=[full_pipeline_job],
)
def run_failure_sensor(context: dg.RunFailureSensorContext):
    """Mark a request failed when its run does.

    Without this a failed run leaves its request `running` forever: the sensor
    will not re-emit it (the run key is spent) and nothing else would move it.
    A failed request is deliberately not made pending again — retrying is a new
    request, so a permanently broken configuration cannot loop.
    """
    request_id = request_id_of(dict(context.dagster_run.tags))
    if not request_id:
        return

    from phases_v2.requests.domain import mark_failed
    from phases_v2.requests.factory import request_store

    engine = _engine()
    if not engine.services.dataset_available():
        return
    mark_failed(
        request_store(engine),
        request_id,
        context.failure_event.message or "the run failed",
    )


class PhasesV2Orchestration(DagsterOrchestration):
    @classmethod
    def New(cls) -> "PhasesV2Orchestration":
        return cls(
            definitions=dg.Definitions(
                jobs=[
                    ingest_papers_job,
                    chunk_papers_job,
                    run_extraction_job,
                    project_graph_job,
                    project_vectors_job,
                    full_pipeline_job,
                ],
                sensors=[run_request_sensor, run_failure_sensor],
            )
        )
