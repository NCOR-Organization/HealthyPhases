"""The module's dataset schemas.

Every dataset declares a ``primary_key`` and is written with ``mode="upsert"``
(see ``store.write_rows``). The store treats the key as advisory — it matches
upserts against it but enforces no uniqueness — so an ``append`` anywhere would
silently duplicate rows. That is why nothing here is ever appended.

Partitioning follows the column each scoped run filters on, never a per-row id:
partitioning on ``chunk_id`` or ``paper_id`` would put one row in every
partition.
"""

from naas_abi_core.services.dataset.DatasetPort import (
    ColumnSpec,
    DatasetSpec,
    PartitionSpec,
)

NAMESPACE = "phases_v2"


def _spec(
    name: str,
    columns: tuple[tuple[str, str], ...],
    primary_key: tuple[str, ...],
    partitions: tuple[str, ...] = (),
) -> DatasetSpec:
    return DatasetSpec(
        name=name,
        namespace=NAMESPACE,
        columns=tuple(ColumnSpec(name=n, type=t) for n, t in columns),  # type: ignore[arg-type]
        primary_key=primary_key,
        partitions=tuple(PartitionSpec(column=c) for c in partitions),
    )


PAPERS = _spec(
    "papers",
    (
        ("paper_id", "string"),
        ("storage_prefix", "string"),
        ("storage_key", "string"),
        ("file_name", "string"),
        ("content_sha256", "string"),
        ("size_bytes", "bigint"),
        ("mime_type", "string"),
        ("text_key", "string"),
        ("discovered_at", "timestamp"),
    ),
    primary_key=("paper_id",),
)

CHUNKERS = _spec(
    "chunkers",
    (
        ("chunker_id", "string"),
        ("name", "string"),
        ("version", "string"),
        ("params", "json"),
        ("registered_at", "timestamp"),
    ),
    primary_key=("chunker_id",),
)

CHUNKS = _spec(
    "chunks",
    (
        ("chunk_id", "string"),
        ("paper_id", "string"),
        ("chunker_id", "string"),
        ("seq", "integer"),
        ("text", "string"),
        ("char_start", "integer"),
        ("char_end", "integer"),
        ("token_count", "integer"),
    ),
    primary_key=("chunk_id",),
    partitions=("chunker_id",),
)

PROMPTS = _spec(
    "prompts",
    (
        ("prompt_id", "string"),
        ("name", "string"),
        ("prompt_sha256", "string"),
        ("template", "string"),
        ("output_key", "string"),
        ("registered_at", "timestamp"),
    ),
    primary_key=("prompt_id",),
)

MODELS = _spec(
    "models",
    (
        ("model_id", "string"),
        ("provider", "string"),
        ("provider_model_id", "string"),
        ("display_name", "string"),
        ("registered_at", "timestamp"),
    ),
    primary_key=("model_id",),
)

EXTRACTION_RUNS = _spec(
    "extraction_runs",
    (
        ("run_id", "string"),
        ("chunker_id", "string"),
        ("model_id", "string"),
        ("prompt_id", "string"),
        ("started_at", "timestamp"),
        ("finished_at", "timestamp"),
        ("succeeded", "integer"),
        ("failed", "integer"),
        ("skipped", "integer"),
    ),
    primary_key=("run_id",),
)

EXTRACTIONS = _spec(
    "extractions",
    (
        ("extraction_id", "string"),
        ("chunk_id", "string"),
        ("model_id", "string"),
        ("prompt_id", "string"),
        ("run_id", "string"),
        ("status", "string"),
        # The model's output, kept twice on purpose. `response` is the parsed
        # object, queryable with json_extract and friends — NULL when the model
        # returned something unparseable. `raw_response` is always exactly what
        # came back, which is what makes a failed extraction re-parseable later
        # without paying for the call again.
        ("response", "json"),
        ("raw_response", "string"),
        ("error", "string"),
        ("item_count", "integer"),
        ("completed_at", "timestamp"),
    ),
    primary_key=("extraction_id",),
    partitions=("prompt_id",),
)

EXTRACTED_ITEMS = _spec(
    "extracted_items",
    (
        ("item_id", "string"),
        ("extraction_id", "string"),
        ("chunk_id", "string"),
        ("paper_id", "string"),
        ("prompt_id", "string"),
        ("seq", "integer"),
        ("text", "string"),
    ),
    primary_key=("item_id",),
    partitions=("prompt_id",),
)

PROJECTIONS = _spec(
    "projections",
    (
        # "graph" | "vector_chunks" | "vector_items"
        ("target", "string"),
        ("key", "string"),
        ("projected_at", "timestamp"),
    ),
    primary_key=("target", "key"),
)

RUN_REQUESTS = _spec(
    "run_requests",
    (
        ("request_id", "string"),
        # "pending" | "running" | "succeeded" | "failed"
        ("status", "string"),
        ("locations", "json"),
        ("chunker_id", "string"),
        # A run covers several prompts — extracting only one dimension of a
        # corpus at a time is the exception, not the default.
        ("prompt_ids", "json"),
        ("model_id", "string"),
        ("requested_by", "string"),
        ("requested_at", "timestamp"),
        ("started_at", "timestamp"),
        ("finished_at", "timestamp"),
        ("run_id", "string"),
        ("error", "string"),
    ),
    primary_key=("request_id",),
)

INPUT_LOCATIONS = _spec(
    "input_locations",
    (("prefix", "string"), ("name", "string"), ("created_at", "timestamp")),
    primary_key=("prefix",),
)

PIPELINES = _spec(
    "pipelines",
    (
        ("pipeline_id", "string"),
        ("name", "string"),
        ("inputs", "json"),
        ("created_at", "timestamp"),
    ),
    primary_key=("pipeline_id",),
)

DATASETS: tuple[DatasetSpec, ...] = (
    PAPERS,
    CHUNKERS,
    CHUNKS,
    PROMPTS,
    MODELS,
    EXTRACTION_RUNS,
    EXTRACTIONS,
    EXTRACTED_ITEMS,
    PROJECTIONS,
    RUN_REQUESTS,
    INPUT_LOCATIONS,
    PIPELINES,
)
