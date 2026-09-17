"""PubMed requests and opted-in recurring searches; no Phase v2 scheduling."""

import dagster as dg
from naas_abi_core.orchestrations.DagsterOrchestration import DagsterOrchestration

BACKFILL_TAG = "pubmed/backfill_id"
GENERATION_TAG = "pubmed/backfill_generation"
TAG = "pubmed/request_id"
SCHEDULE_TAG = "pubmed/schedule_id"
SCHEDULED_AT_TAG = "pubmed/scheduled_at"


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


def schedules():
    from pubmed.application.pubmed_schedules import PubmedSchedules

    return PubmedSchedules(service())


class ScheduleConfig(dg.Config):
    schedule_id: str
    scheduled_at: str


@dg.op
def refresh_query(context: dg.OpExecutionContext, config: ScheduleConfig):
    row = schedules().execute(config.schedule_id, config.scheduled_at, context.run_id)
    context.log.info(
        "Scheduled query completed" if row else "Schedule disabled or already claimed"
    )


@dg.job(name="pubmed_scheduled_query")
def scheduled_query_job():
    refresh_query()


def build_schedule_run_requests(due):
    return [
        dg.RunRequest(
            run_key=f"{row['schedule_id']}:{row['next_run_at']}",
            tags={
                SCHEDULE_TAG: row["schedule_id"],
                SCHEDULED_AT_TAG: row["next_run_at"],
            },
            run_config={
                "ops": {
                    "refresh_query": {
                        "config": {
                            "schedule_id": row["schedule_id"],
                            "scheduled_at": row["next_run_at"],
                        }
                    }
                }
            },
        )
        for row in due
    ]


@dg.sensor(
    name="pubmed_schedule_sensor",
    job=scheduled_query_job,
    minimum_interval_seconds=30,
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def schedule_sensor(context):
    from naas_abi_core.apps.dagster.dagster import engine

    if not engine.services.dataset_available():
        return dg.SkipReason("DatasetService unavailable")
    due = schedules().due()[:1]
    return (
        build_schedule_run_requests(due)
        if due
        else dg.SkipReason("No scheduled queries due")
    )


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


def backfills():
    from pubmed.application.pubmed_backfills import PubmedBackfills

    return PubmedBackfills(service())


class BackfillConfig(dg.Config):
    backfill_id: str
    generation: int


@dg.op
def advance_backfill(context: dg.OpExecutionContext, config: BackfillConfig):
    row = backfills().execute(config.backfill_id, config.generation, context.run_id)
    context.log.info(f"Full ingestion: {row['status'] if row else 'already claimed'}")


@dg.job(name="pubmed_backfill")
def backfill_job():
    advance_backfill()


def build_backfill_run_requests(due):
    return [
        dg.RunRequest(
            run_key=f"{row['backfill_id']}:{row['generation']}",
            tags={
                BACKFILL_TAG: row["backfill_id"],
                GENERATION_TAG: str(row["generation"]),
            },
            run_config={
                "ops": {
                    "advance_backfill": {
                        "config": {
                            "backfill_id": row["backfill_id"],
                            "generation": row["generation"],
                        }
                    }
                }
            },
        )
        for row in due
    ]


@dg.sensor(
    name="pubmed_backfill_sensor",
    job=backfill_job,
    minimum_interval_seconds=30,
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def backfill_sensor(context):
    from naas_abi_core.apps.dagster.dagster import engine

    if not engine.services.dataset_available():
        return dg.SkipReason("DatasetService unavailable")
    due = backfills().due()[:1]
    return (
        build_backfill_run_requests(due)
        if due
        else dg.SkipReason("No full ingestion ready to advance")
    )


def fail_backfill_run(run, message):
    backfill_id = run.tags.get(BACKFILL_TAG)
    if backfill_id:
        backfills().fail(
            backfill_id, int(run.tags[GENERATION_TAG]), run.run_id, message
        )


@dg.run_failure_sensor(
    name="pubmed_failure_sensor",
    monitored_jobs=[publication_job, scheduled_query_job, backfill_job],
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def failure_sensor(context):
    fail_backfill_run(
        context.dagster_run,
        "Full ingestion interrupted; inspect the Dagster run and resume",
    )
    request_id = context.dagster_run.tags.get(TAG)
    if request_id:
        service().fail(
            request_id, context.failure_event.message, context.dagster_run.run_id
        )
    schedule_id = context.dagster_run.tags.get(SCHEDULE_TAG)
    if schedule_id:
        schedules().fail(
            schedule_id,
            context.dagster_run.run_id,
            "Scheduled search failed; inspect the Dagster run",
            context.dagster_run.tags.get(SCHEDULED_AT_TAG, ""),
        )


@dg.run_status_sensor(
    name="pubmed_cancellation_sensor",
    run_status=dg.DagsterRunStatus.CANCELED,
    monitored_jobs=[publication_job, scheduled_query_job, backfill_job],
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def cancellation_sensor(context):
    fail_backfill_run(
        context.dagster_run,
        "Full ingestion canceled; resume to continue from its checkpoint",
    )
    request_id = context.dagster_run.tags.get(TAG)
    if request_id:
        service().fail(
            request_id, "The PubMed run was canceled", context.dagster_run.run_id
        )
    schedule_id = context.dagster_run.tags.get(SCHEDULE_TAG)
    if schedule_id:
        schedules().fail(
            schedule_id,
            context.dagster_run.run_id,
            "Scheduled search was canceled",
            context.dagster_run.tags.get(SCHEDULED_AT_TAG, ""),
        )


class PubmedOrchestration(DagsterOrchestration):
    @classmethod
    def New(cls):
        return cls(
            definitions=dg.Definitions(
                jobs=[publication_job, scheduled_query_job, backfill_job],
                sensors=[
                    backfill_sensor,
                    request_sensor,
                    schedule_sensor,
                    failure_sensor,
                    cancellation_sensor,
                ],
            )
        )
