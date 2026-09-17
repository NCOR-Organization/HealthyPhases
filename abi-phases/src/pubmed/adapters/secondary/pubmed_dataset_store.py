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
    "backfills": ("BackfillRecord", ("backfill_id",)),
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

    def recent_requests(self, limit=100):
        return self.dataset.query(
            f"SELECT * FROM run_requests ORDER BY requested_at DESC LIMIT {int(limit)}",
            namespace=NAMESPACE,
        ).rows

    def browse_papers(self, filters):
        clauses = []
        if filters["status"] != "all":
            clauses.append(
                "a.pmid IS "
                + ("NOT NULL" if filters["status"] == "published" else "NULL")
            )
        if filters["query_id"]:
            clauses.append(
                "EXISTS (SELECT 1 FROM query_papers m WHERE m.pmid = p.pmid "
                f"AND m.query_id = {literal(filters['query_id'])})"
            )
        if filters["search"].strip():
            # Literal substring search: percent/underscore are not SQL wildcards.
            needle = literal(filters["search"].strip().lower())
            clauses.append(
                "("
                + " OR ".join(
                    f"contains(lower(COALESCE(CAST(p.{column} AS VARCHAR), '')), {needle})"
                    for column in (
                        "title",
                        "authors",
                        "journal",
                        "pmid",
                        "pmcid",
                        "doi",
                    )
                )
                + ")"
            )
        for key, operator in (("ingested_from", ">="), ("ingested_until", "<=")):
            if filters[key]:
                clauses.append(
                    f"SUBSTR(a.last_ingested_at, 1, 10) {operator} {literal(filters[key])}"
                )
        order = {
            "newest": "last_ingested_at DESC NULLS LAST, pmid",
            "oldest": "last_ingested_at ASC NULLS LAST, pmid",
            "title": "lower(title), pmid",
        }[filters["sort"]]
        limit = int(filters["page_size"])
        offset = (int(filters["page"]) - 1) * limit
        # Count and page share one SQL snapshot, including an empty/out-of-range page.
        rows = self.dataset.query(
            "WITH filtered AS (SELECT p.*, a.last_ingested_at FROM papers p "
            "LEFT JOIN (SELECT pmid, MAX(NULLIF(published_at, '')) AS last_ingested_at "
            "FROM artifacts WHERE status = 'ready' AND contract_version = 1 GROUP BY pmid) a "
            "ON a.pmid = p.pmid "
            + ("WHERE " + " AND ".join(clauses) if clauses else "")
            + ") "
            "SELECT counts.total, page.* FROM (SELECT COUNT(*) AS total FROM filtered) counts "
            f"LEFT JOIN (SELECT * FROM filtered ORDER BY {order} LIMIT {limit} OFFSET {offset}) page "
            f"ON TRUE ORDER BY {order}",
            namespace=NAMESPACE,
        ).rows
        total = rows[0]["total"]
        return total, [
            {
                k: (v or "") if k == "last_ingested_at" else v
                for k, v in row.items()
                if k != "total"
            }
            for row in rows
            if row["pmid"] is not None
        ]

    def members(self, query_id, pmids=None, limit=1001):
        clause = f"query_id = {literal(query_id)}"
        if pmids is not None:
            if not pmids:
                return []
            clause += " AND pmid IN (" + ",".join(literal(p) for p in pmids) + ")"
        return self.dataset.query(
            f"SELECT * FROM query_papers WHERE {clause} ORDER BY pmid LIMIT {int(limit)}",
            namespace=NAMESPACE,
        ).rows

    def member_count(self, query_id):
        return self.dataset.query(
            f"SELECT COUNT(*) AS n FROM query_papers WHERE query_id = {literal(query_id)}",
            namespace=NAMESPACE,
        ).rows[0]["n"]

    def rows_for_pmids(self, table, pmids):
        if table not in {"papers", "artifacts"}:
            raise ValueError("Unsupported PMID lookup")
        if not pmids:
            return []
        identifiers = ",".join(literal(p) for p in pmids)
        return self.dataset.query(
            f"SELECT * FROM {table} WHERE pmid IN ({identifiers})", namespace=NAMESPACE
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

    def update_backfill(self, backfill_id, change):
        return self._conditional_update("backfills", "backfill_id", backfill_id, change)

    def create_request(self, row):
        return self._conditional_update(
            "run_requests",
            "request_id",
            row["request_id"],
            lambda current: current or row,
            allow_missing=True,
        )

    def _conditional_update(self, table, key, value, change, allow_missing=False):
        for attempt in range(5):
            snapshot = self.dataset.describe(table, namespace=NAMESPACE).snapshot_id
            rows = self.rows(table, **{key: value})
            if not rows and not allow_missing:
                raise PublicationNotFound(value)
            record = validate(TABLES[table][0], change(rows[0] if rows else None))
            try:
                self.dataset.write(
                    table,
                    [record],
                    namespace=NAMESPACE,
                    mode="upsert",
                    snapshot_id=snapshot,
                )
                return record
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
