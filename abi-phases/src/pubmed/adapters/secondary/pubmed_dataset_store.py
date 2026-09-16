"""DatasetService persistence; table shapes are derived from the .proto records."""

from datetime import UTC, datetime
from time import sleep

from google.protobuf.descriptor import FieldDescriptor
from naas_abi_core.services.dataset.DatasetPort import (
    ColumnSpec,
    DatasetAlreadyExistsError,
    DatasetNotFoundError,
    DatasetSnapshotConflictError,
    DatasetSpec,
)

from pubmed.contracts.pubmed_validation import message_type, validate
from pubmed.domain.pubmed_errors import PublicationNotFound, RequestAlreadyClaimed

NAMESPACE = "pubmed"
TABLES = {
    "queries": ("QueryRecord", ("query_id",)),
    "papers": ("PaperRecord", ("pmid",)),
    "query_papers": ("MembershipRecord", ("query_id", "pmid")),
    "artifacts": ("ArtifactRecord", ("artifact_id",)),
    "run_requests": ("RequestRecord", ("request_id",)),
    "schedules": ("ScheduleRecord", ("schedule_id",)),
}


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def specs():
    for name, (message, keys) in TABLES.items():
        columns = []
        for field in message_type(message).DESCRIPTOR.fields:
            kind = "string"
            if field.is_repeated or field.type == FieldDescriptor.TYPE_MESSAGE:
                kind = "json"
            elif field.type == FieldDescriptor.TYPE_INT32:
                kind = "integer"
            elif field.type == FieldDescriptor.TYPE_INT64:
                kind = "bigint"
            elif field.type == FieldDescriptor.TYPE_BOOL:
                kind = "boolean"
            columns.append(ColumnSpec(name=field.name, type=kind))
        yield DatasetSpec(
            name=name, namespace=NAMESPACE, columns=tuple(columns), primary_key=keys
        )


class PubmedDatasetStore:
    def __init__(self, dataset):
        self.dataset = dataset

    def ensure(self):
        for spec in specs():
            try:
                self.dataset.describe(spec.name, namespace=NAMESPACE)
            except DatasetNotFoundError:
                try:
                    self.dataset.create(spec)
                except DatasetAlreadyExistsError:
                    pass

    def rows(self, table, **filters):
        if table not in TABLES:
            raise ValueError("Unknown publication table")
        columns = {f.name for f in message_type(TABLES[table][0]).DESCRIPTOR.fields}
        if not filters.keys() <= columns:
            raise ValueError("Unknown publication filter")
        where = " AND ".join(
            f"{key} = {literal(value)}" for key, value in filters.items()
        )
        return self.dataset.query(
            f"SELECT * FROM {table}" + (f" WHERE {where}" if where else ""),
            namespace=NAMESPACE,
        ).rows

    def save(self, table, records):
        if records:
            records = [validate(TABLES[table][0], row) for row in records]
            self.dataset.write(table, records, namespace=NAMESPACE, mode="upsert")

    def claim(self, request_id, run_id):
        for attempt in range(5):
            snapshot = self.dataset.describe(
                "run_requests", namespace=NAMESPACE
            ).snapshot_id
            rows = self.dataset.query(
                f"SELECT * FROM run_requests WHERE request_id = {literal(request_id)}",
                namespace=NAMESPACE,
                snapshot_id=snapshot,
            ).rows
            if not rows:
                raise PublicationNotFound(request_id)
            row = rows[0]
            if row["status"] != "pending":
                raise RequestAlreadyClaimed(request_id)
            row.update(
                status="running",
                run_id=run_id,
                started_at=datetime.now(UTC).isoformat(),
            )
            try:
                self.dataset.write(
                    "run_requests",
                    [row],
                    namespace=NAMESPACE,
                    mode="upsert",
                    snapshot_id=snapshot,
                )
                return row
            except DatasetSnapshotConflictError:
                if attempt == 4:
                    raise
                sleep(0.05 * (attempt + 1))

    def update_schedule(self, schedule_id, change):
        for attempt in range(5):
            snapshot = self.dataset.describe(
                "schedules", namespace=NAMESPACE
            ).snapshot_id
            rows = self.dataset.query(
                f"SELECT * FROM schedules WHERE schedule_id = {literal(schedule_id)}",
                namespace=NAMESPACE,
            ).rows
            # The write checks the token captured before this read. Any intervening
            # commit forces a retry without attaching a second historical catalog.
            if not rows:
                raise PublicationNotFound(schedule_id)
            row = validate("ScheduleRecord", change(rows[0]))
            try:
                self.dataset.write(
                    "schedules",
                    [row],
                    namespace=NAMESPACE,
                    mode="upsert",
                    snapshot_id=snapshot,
                )
                return row
            except DatasetSnapshotConflictError:
                if attempt == 4:
                    raise
                sleep(0.05 * (attempt + 1))

    def delete_schedule(self, schedule_id):
        for attempt in range(5):
            snapshot = self.dataset.describe(
                "schedules", namespace=NAMESPACE
            ).snapshot_id
            rows = self.rows("schedules")
            remaining = [row for row in rows if row["schedule_id"] != schedule_id]
            if len(remaining) == len(rows):
                raise PublicationNotFound(schedule_id)
            try:
                # The catalog token preserves any concurrent creation or toggle.
                self.dataset.write(
                    "schedules",
                    remaining,
                    namespace=NAMESPACE,
                    mode="replace",
                    snapshot_id=snapshot,
                )
                return
            except DatasetSnapshotConflictError:
                if attempt == 4:
                    raise
                sleep(0.05 * (attempt + 1))
