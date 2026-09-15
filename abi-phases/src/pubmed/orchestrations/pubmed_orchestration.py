"""Only explicit PubMed requests create jobs; no Phase v2 scheduling."""

import dagster as dg
from naas_abi_core.orchestrations.DagsterOrchestration import DagsterOrchestration

TAG = "pubmed/request_id"


def service():
    from naas_abi_core.apps.dagster.dagster import engine

    from pubmed.pubmed_factory import service as build

    module = engine.modules["pubmed"]
    return build(engine, module._configuration)


class RequestConfig(dg.Config):
    request_id: str


@dg.op
def publish_papers(context: dg.OpExecutionContext, config: RequestConfig):
    result = service().execute(config.request_id, context.run_id)
    context.log.info(f"PubMed request {result['request_id']}: {result['status']}")
    return result["status"]


@dg.job(name="pubmed_publish")
def publication_job():
    publish_papers()


def build_run_requests(pending):
    return [
        dg.RunRequest(
            run_key=row["request_id"],
            tags={TAG: row["request_id"]},
            run_config={
                "ops": {"publish_papers": {"config": {"request_id": row["request_id"]}}}
            },
        )
        for row in pending
    ]


@dg.sensor(
    name="pubmed_run_request_sensor",
    job=publication_job,
    minimum_interval_seconds=30,
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def request_sensor(context):
    from naas_abi_core.apps.dagster.dagster import engine

    if not engine.services.dataset_available():
        return dg.SkipReason("DatasetService unavailable")
    publisher = service()
    if publisher.store.rows("run_requests", status="running"):
        return dg.SkipReason("A PubMed request is running")
    pending = sorted(
        publisher.store.rows("run_requests", status="pending"),
        key=lambda r: r["requested_at"],
    )[:1]
    return (
        build_run_requests(pending)
        if pending
        else dg.SkipReason("No pending PubMed requests")
    )


@dg.run_failure_sensor(
    name="pubmed_failure_sensor",
    monitored_jobs=[publication_job],
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def failure_sensor(context):
    request_id = context.dagster_run.tags.get(TAG)
    if request_id:
        service().fail(
            request_id, context.failure_event.message, context.dagster_run.run_id
        )


@dg.run_status_sensor(
    name="pubmed_cancellation_sensor",
    run_status=dg.DagsterRunStatus.CANCELED,
    monitored_jobs=[publication_job],
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def cancellation_sensor(context):
    request_id = context.dagster_run.tags.get(TAG)
    if request_id:
        service().fail(
            request_id, "The PubMed run was canceled", context.dagster_run.run_id
        )


class PubmedOrchestration(DagsterOrchestration):
    @classmethod
    def New(cls):
        return cls(
            definitions=dg.Definitions(
                jobs=[publication_job],
                sensors=[request_sensor, failure_sensor, cancellation_sensor],
            )
        )
