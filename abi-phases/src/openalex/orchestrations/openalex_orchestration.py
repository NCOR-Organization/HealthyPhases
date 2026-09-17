"""One checkpointed batch per run; pending generations are picked up by a sensor."""

import dagster as dg
from naas_abi_core.orchestrations.DagsterOrchestration import DagsterOrchestration

TAG = "openalex/request_id"
GENERATION = "openalex/generation"


def service():
    from naas_abi_core.apps.dagster.dagster import engine

    from openalex.openalex_factory import service as build

    return build(engine, engine.modules["openalex"]._configuration)


class EnrichmentConfig(dg.Config):
    request_id: str
    generation: int


@dg.op
def enrich_papers(context: dg.OpExecutionContext, config: EnrichmentConfig):
    row = service().execute(config.request_id, config.generation, context.run_id)
    context.log.info(
        f"OpenAlex enrichment: {row['status'] if row else 'already claimed'}"
    )


@dg.job(name="openalex_enrich")
def enrichment_job():
    enrich_papers()


def build_run_requests(rows):
    return [
        dg.RunRequest(
            run_key=f"{r['request_id']}:{r['generation']}",
            tags={TAG: r["request_id"], GENERATION: str(r["generation"])},
            run_config={
                "ops": {
                    "enrich_papers": {
                        "config": {
                            "request_id": r["request_id"],
                            "generation": r["generation"],
                        }
                    }
                }
            },
        )
        for r in rows
    ]


@dg.sensor(
    name="openalex_enrichment_sensor",
    job=enrichment_job,
    minimum_interval_seconds=30,
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def enrichment_sensor(context):
    from naas_abi_core.apps.dagster.dagster import engine

    if not engine.services.dataset_available():
        return dg.SkipReason("DatasetService unavailable")
    due = service().due()
    return (
        build_run_requests(due)
        if due
        else dg.SkipReason("No OpenAlex enrichment ready")
    )


def fail_run(run):
    if TAG in run.tags:
        service().fail(
            run.tags[TAG],
            int(run.tags[GENERATION]),
            run.run_id,
            "Enrichment interrupted; resume to continue from the saved checkpoint",
        )


@dg.run_failure_sensor(
    name="openalex_failure_sensor",
    monitored_jobs=[enrichment_job],
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def failure_sensor(context):
    fail_run(context.dagster_run)


@dg.run_status_sensor(
    name="openalex_cancellation_sensor",
    run_status=dg.DagsterRunStatus.CANCELED,
    monitored_jobs=[enrichment_job],
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def cancellation_sensor(context):
    fail_run(context.dagster_run)


class OpenalexOrchestration(DagsterOrchestration):
    @classmethod
    def New(cls):
        return cls(
            definitions=dg.Definitions(
                jobs=[enrichment_job],
                sensors=[enrichment_sensor, failure_sensor, cancellation_sensor],
            )
        )
