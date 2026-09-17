"""Versioned enrichment datasets and catalog-token ownership fencing."""

from time import sleep

from google.protobuf.descriptor import FieldDescriptor
from naas_abi_core.services.dataset.DatasetPort import (
    ColumnSpec,
    DatasetAlreadyExistsError,
    DatasetNotFoundError,
    DatasetSnapshotConflictError,
    DatasetSpec,
)

from openalex.contracts.openalex_validation import message_type, validate
from openalex.domain.openalex_errors import EnrichmentNotFound
from openalex.domain.openalex_ownership import owned

NAMESPACE = "openalex"
TABLES = {
    "works": ("WorkRecord", ("work_id",)),
    "paper_enrichments": ("PaperEnrichment", ("pmid",)),
    "run_requests": ("RequestRecord", ("request_id",)),
    "request_results": ("ResultRecord", ("request_id", "pmid")),
}


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def specs():
    for name, (message, keys) in TABLES.items():
        columns = []
        for f in message_type(message).DESCRIPTOR.fields:
            kind = (
                "json"
                if f.is_repeated or f.type == FieldDescriptor.TYPE_MESSAGE
                else {
                    FieldDescriptor.TYPE_INT32: "integer",
                    FieldDescriptor.TYPE_INT64: "bigint",
                    FieldDescriptor.TYPE_BOOL: "boolean",
                }.get(f.type, "string")
            )
            columns.append(ColumnSpec(name=f.name, type=kind))
        yield DatasetSpec(
            name=name, namespace=NAMESPACE, columns=tuple(columns), primary_key=keys
        )


class OpenalexDatasetStore:
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
        if table not in TABLES or not filters.keys() <= {
            f.name for f in message_type(TABLES[table][0]).DESCRIPTOR.fields
        }:
            raise ValueError("Unknown enrichment table or filter")
        where = " AND ".join(
            f"{key} = {literal(value)}" for key, value in filters.items()
        )
        return self.dataset.query(
            f"SELECT * FROM {table}" + (f" WHERE {where}" if where else ""),
            namespace=NAMESPACE,
        ).rows

    def save(self, table, records):
        self.dataset.write(
            table,
            [validate(TABLES[table][0], r) for r in records],
            namespace=NAMESPACE,
            mode="upsert",
        )

    def update_request(self, request_id, change):
        for attempt in range(5):
            snapshot = self.dataset.describe(
                "run_requests", namespace=NAMESPACE
            ).snapshot_id
            rows = self.rows("run_requests", request_id=request_id)
            if not rows:
                raise EnrichmentNotFound(request_id)
            result = validate("RequestRecord", change(rows[0]))
            try:
                self.dataset.write(
                    "run_requests",
                    [result],
                    namespace=NAMESPACE,
                    mode="upsert",
                    snapshot_id=snapshot,
                )
                return result
            except DatasetSnapshotConflictError:
                if attempt == 4:
                    raise
                sleep(0.05 * (attempt + 1))

    def save_owned(self, table, records, owner):
        for attempt in range(5):
            snapshot = self.dataset.describe(table, namespace=NAMESPACE).snapshot_id
            owned(self.rows("run_requests", request_id=owner["request_id"])[0], owner)
            try:
                self.dataset.write(
                    table,
                    [validate(TABLES[table][0], r) for r in records],
                    namespace=NAMESPACE,
                    mode="upsert",
                    snapshot_id=snapshot,
                )
                return
            except DatasetSnapshotConflictError:
                if attempt == 4:
                    raise
                sleep(0.05 * (attempt + 1))
