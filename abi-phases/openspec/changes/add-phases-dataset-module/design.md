## Context

See proposal.md — Why.

What shapes the approach, all verified against the current tree:

- **`src/phases` stays.** It keeps its named graphs, its vector collections, its `reverse_search` app and its `PhasesOrchestration` Dagster definitions. The new module must not write anywhere it writes.
- **The dataset service is DuckLake-backed.** `DatasetPort` offers `append`, `replace` and `upsert`; `DatasetSpec` carries a `primary_key`; `ColumnType` includes `json`; snapshots are monotonically increasing integers at the **catalog** level, and `query(snapshot_id=...)` reads the whole catalog at that version.
- **`primary_key` is advisory.** The store does not enforce uniqueness — the key only drives the upsert match. An `append` into a keyed dataset still duplicates, silently.
- **Snapshots are catalog-wide.** Any write to any dataset advances the counter, so the write-time `snapshot_id` is a whole-catalog compare-and-swap token, not a per-dataset version.
- **Object storage listing is depth-1.** S3/R2 pass `Delimiter="/"` (`ObjectStorageSecondaryAdapterS3.py:206`); FS uses `os.listdir` (`ObjectStorageSecondaryAdapterFS.py:100`). There is no recursive primitive.
- **The vector store upserts by id.** `SqliteVecAdapter.store_vectors` uses `INSERT OR REPLACE`, and Qdrant upserts by point id.
- **Dagster sensors already have a working pattern here.** `XSearchRecentTweetsFilesOrchestration.py:446` uses `@dg.sensor` returning `[dg.RunRequest(run_key=...)]`, wired through `Definitions(sensors=[...])`. Dagster will not start a second run for a `run_key` it has already seen.
- **Nexus's datasets API is read-only** — list, describe, preview, query. It can browse the pipeline but cannot start it.
- **The dataset warehouse no longer overlaps object storage.** Upstream defaults put it at `storage/datasets/`, a sibling of the object-storage root at `storage/datastore`, so recursive paper discovery cannot wander into it.

## Goals / Non-Goals

**Goals:**
- Make the datasets the system of record, and the triple store and vector collections rebuildable projections of them.
- Make every stage of the pipeline resumable and re-runnable at zero cost for work already done.
- Keep the domain unaware of DuckLake, Dagster, Oxigraph, sqlite-vec and the LLM SDK, per the project's hexagonal guidelines.
- Leave `src/phases` byte-for-byte unmodified.

**Non-Goals:**
- Changing the core dataset service. Upsert, the `json` column type and catalog snapshots are upstream capabilities this change consumes.
- Migrating existing v1 data into the new datasets. The new module starts empty.
- A union query surface across v1 and v2 graphs.
- Retiring, deprecating, or feature-freezing `src/phases`.

## Decisions

### D1 — Datasets are the system of record; graph and vectors are projections

Everything the pipeline produces lands in a dataset first. The triple store and the vector collections are written *from* those datasets and can be dropped and rebuilt without data loss.

*Alternative considered:* keep the triple store as the system of record, as v1 does. Rejected — it gives no SQL surface for the UI, no ledger of completed work, and makes prompt versioning invisible.

### D2 — One namespace, ten datasets, every one keyed

Namespace `phases_v2`. Every dataset declares a `primary_key` and is written with `mode="upsert"`.

| Dataset | Grain | Primary key | Notable columns |
|---|---|---|---|
| `papers` | one source document | `paper_id` | storage prefix/key, `content_sha256`, size, mime, `text_key`, `discovered_at` |
| `chunkers` | one chunking mechanism version | `chunker_id` | `name`, `version`, `params` (json), `registered_at` |
| `chunks` | one chunk | `chunk_id` | `paper_id`, `chunker_id`, `seq`, `text`, offsets |
| `prompts` | one prompt version | `prompt_id` | `name`, `prompt_sha256`, `template`, `output_key`, `registered_at` |
| `models` | one declared model | `model_id` | `provider`, `provider_model_id`, `display_name` |
| `extraction_runs` | one invocation | `run_id` | scope, timings, succeeded/failed/skipped |
| `extractions` | one chunk × model × prompt | `extraction_id` | `chunk_id`, `model_id`, `prompt_id`, `run_id`, `status`, `response` (json), `raw_response`, `error`, `item_count` |
| `extracted_items` | one extracted item | `item_id` | `extraction_id`, `chunk_id`, `paper_id`, `seq`, `text` |
| `projections` | one projected key per target | `target` + `key` | `projected_at` |
| `run_requests` | one requested run | `request_id` | `status`, `locations` (json), `chunker_id`, `prompt_id`, `model_id`, `requested_by`, timestamps, `run_id` |

### D3 — Content-addressed identifiers everywhere

| Id | Derivation |
|---|---|
| `paper_id` | `sha256(content bytes)` |
| `chunker_id` | `{name}_{version}_{sha256(canonical params json)[:12]}` |
| `chunk_id` | `sha256(f"{paper_id}:{chunker_id}:{seq}")` |
| `prompt_id` | `{name}_{sha256(template)[:12]}` |
| `model_id` | the ABI model registry canonical id |
| `extraction_id` | `sha256(f"{chunk_id}:{model_id}:{prompt_id}")` |
| `item_id` | `sha256(f"{extraction_id}:{seq}")` |

One identity works in all four places: the dataset primary key, the vector id, the local name of the RDF URI, and the Dagster `run_key`. That is what lets every stage be idempotent without a distributed transaction.

*Alternative considered:* random UUIDs plus a lookup table. Rejected — deduplication would need a stateful join through that table, and re-running would not be naturally free.

### D4 — Deduplication is a SQL anti-join

Datasets in one namespace are queryable together, so the outstanding work for a run is one query:

```sql
SELECT c.chunk_id
FROM chunks c
LEFT JOIN extractions e
  ON  e.chunk_id  = c.chunk_id
  AND e.model_id  = :model_id
  AND e.prompt_id = :prompt_id
  AND e.status    = 'succeeded'
WHERE c.chunker_id = :chunker_id
  AND e.extraction_id IS NULL
```

Failed rows are absent from the join and so are retried, which is the behavior the extraction spec requires.

Note the division of labour: **upsert prevents duplicate rows, this query prevents duplicate *work*.** They are not substitutes — without the query, an already-extracted chunk would be sent to the model again and merely overwrite its own row, having paid for the call.

*Alternative considered:* a filesystem or key-value ledger, as v1 does with `CacheFactory.CacheFS_find_storage`. Rejected — a side cache can drift from the data it describes. The dataset *is* the ledger, so it cannot.

### D5 — Model output is stored three ways, and the third one was not optional

`extractions.response` is a `json` column holding the parsed response. `extractions.raw_response` is a string holding exactly what the model returned. `extracted_items` holds one row per item.

The JSON column keeps the response queryable — `json_extract`, `json_array_length` and friends work on it directly — so a change in how output is interpreted never means paying for the model call again. The exploded rows exist because each item needs an identity of its own: `item_id` is the vector id and the RDF URI local name, and the rows are the join target for both projectors.

`raw_response` was added during implementation, after the integration test caught the flaw: a `json` column **rejects unparseable output**, which is precisely the case where keeping the model's exact words matters most. Storing only `response` meant a malformed answer could not be recorded at all, so the "re-parse later instead of re-paying" property held for every case except the one that needs it. On a success both columns are populated; on a parse failure `response` is NULL and `raw_response` carries the text.

*Alternatives considered:* JSON only — rejected, as above, and it cannot represent a failure. Items only — rejected, an unrecoverable loss of the model's actual output. Wrapping bad output as `{"raw": "..."}` to keep one column — rejected, it makes the column's shape depend on whether parsing happened, so every reader has to handle both.

### D6 — Every write is an upsert; `append` is never used

`primary_key` is advisory, so the store will happily let an `append` duplicate a keyed row. The module therefore uses `mode="upsert"` for every dataset write, without exception, and treats `append` as unavailable.

This is what makes the whole design simple:

- **Registries** — prompts, chunkers and models re-register on every module load, in every process that starts the engine (API, Dagster daemon, each run worker). An upsert makes that a no-op rather than something needing a read-then-diff guard.
- **Ledgers** — a retried extraction, or two runs overlapping on the same scope, converge on one row instead of producing duplicates that readers must later collapse.
- **Interrupted stages** — re-running writes the same keys and lands in the same state.

The one thing to preserve is ordering: `extracted_items` is written before the `extractions` row, so the row that deduplication reads is the last thing to appear. A crash between them leaves the work outstanding and it is simply redone.

*Rejected:* the write-time `snapshot_id` as a concurrency token. It is a catalog-wide compare-and-swap, so an unrelated write to `papers` would invalidate a token taken for `extractions`. With upsert there is nothing for it to protect.

### D7 — Partition on the dominant filter, never on an id

`chunks` partitions on `chunker_id`; `extractions` and `extracted_items` partition on `prompt_id`. Both are low-cardinality and are the columns every scoped run filters on. `papers`, the registries and the two small operational datasets are unpartitioned.

Partitioning on `paper_id` or `chunk_id` would create one partition per row, which is the failure mode the identity transform invites.

### D8 — Projections are idempotent by construction, incremental by ledger, coherent by snapshot

Three separate properties, each with its own mechanism:

- **Idempotent** — RDF is a set and vector ids are deterministic, so re-writing the same projection changes nothing. This follows from D3 alone.
- **Incremental** — the `projections` dataset records `(target, key, projected_at)`, and each projector processes only keys it has not recorded. Embeddings are the expensive part, so this is what makes a re-run cheap rather than merely correct.
- **Coherent** — a projector takes the current snapshot once at the start of the run and reads every dataset at that `snapshot_id`. Without this a run could read an `extractions` row whose `extracted_items` had not yet been written, and project an extraction with no items.

That third property is why the ordering rule in D6 is a safety net rather than the primary mechanism.

*Alternative considered:* ask the target store what it already holds — a SPARQL query for existing `extraction_id`s, or a vector-store lookup. Rejected — it does not scale, and it makes the projector's correctness depend on the target's query semantics.

### D9 — Separate named graphs, shared vocabulary

The module writes to `http://ontology.naas.ai/graph/phases/v2/papers` and `http://ontology.naas.ai/graph/phases/v2/extractions`, mirroring v1's naming with a `v2` segment.

The module carries **its own copy** of the ontology TTLs under `src/phases_v2/ontologies/`, so it is self-sufficient and can evolve them without touching v1 — but it keeps the **same class and property URIs** (the existing `documents.owl#` namespace). Graphs are separate; vocabulary is shared. Composer queries written against v1's shapes work against v2's graphs by changing only the `GRAPH` clause.

Unlike v1, the module does **not** regenerate its ontology Python at load time. The generated classes are committed, which removes v1's `_regenerate_ontologies()` hashing dance and its container file-watcher churn from the new module entirely.

*Alternative considered:* import `phases.ontologies` directly. Rejected — it couples a module we promised not to disturb into the new one's load path, and v1 rewrites those files at import time.

### D10 — The app records a request; a sensor turns it into a run

The app writes a `run_requests` row with `status='pending'` and returns its `request_id`. A Dagster sensor polls for pending rows and emits `RunRequest(run_key=request_id, run_config=…)` for each. The job marks the row `running`, then `succeeded` or `failed`.

This is better than having the app launch a run directly, in four ways:

- **The app never talks to the orchestrator.** No GraphQL client, no endpoint configuration, no failure mode where the app is up and Dagster is not — a request submitted while Dagster is down is picked up when it returns.
- **Exactly-once is free.** Dagster will not start a second run for a `run_key` it has already seen, so a sensor that observes the same pending row twice cannot double-launch it. That guarantee is the reason `request_id` is the `run_key`.
- **The request is durable and auditable.** It is a dataset row, so who asked for what and when is queryable alongside everything else the pipeline records.
- **It composes with the rest of the design.** The request is upserted like every other row and needs no separate mechanism.

*Alternative considered:* the app posting a `launchRun` GraphQL mutation to the Dagster webserver. Rejected — it couples the app to the orchestrator's API and version, needs credentials in the app tier, and gives no durability if the launch fails.

*Alternative considered:* the browser calling Dagster directly. Rejected — it exposes the orchestrator to the browser and needs CORS and auth that do not exist here.

The module still defines the jobs themselves — `ingest_papers`, `chunk_papers`, `run_extraction`, `project_graph`, `project_vectors`, and a `full_pipeline` chaining them — so they remain runnable from the Dagster UI without a request row.

### D11 — Recursive listing lands on the core port

`list_objects_recursive(prefix)` is added to `IObjectStorageAdapter`, `IObjectStorageDomain` and `ObjectStorageService`, implemented in the FS, S3, R2 and Naas adapters, and covered by a shared conformance suite the way the dataset service already does it in `services/dataset/tests/`.

S3 and R2 drop the `Delimiter` and paginate; FS walks. This is a `.abi` submodule change and needs upstreaming.

*Alternative considered:* a recursive walk inside `phases_v2` over the depth-1 primitive. Rejected — it costs one round trip per directory level against S3, and every future module would rewrite it.

### D12 — Module layout follows the project's hexagonal conventions

`src/phases_v2/` is organized by domain — `papers/`, `chunking/`, `prompts/`, `extraction/`, `projection/`, `requests/` — each holding its own interfaces, domain implementation, primary and secondary adapters, factories, fakes, and a `_test.py` beside every file. Each domain that has a secondary adapter also carries a generic adapter test suite, so a second adapter is validated by running it.

Registration of prompts, chunkers and models happens on module load. That load runs in every process that starts the engine, so it must be cheap: with upsert it is one write per registry, with no read first. When `dataset_available()` is `False` the module logs and degrades rather than failing engine boot, mirroring how v1's `api()` swallows wiring errors.

### D13 — Reuse the existing embedding model

Vector collections `phases_v2_chunks` and `phases_v2_extracted_items` use `text-embedding-3-large` at 3072 dimensions — the same as v1 (`src/phases/utils.py`) and the configured default. Same model means v1 and v2 embeddings stay comparable if the two corpora are ever searched together.

## Risks / Trade-offs

- **`primary_key` is advisory, so one stray `append` silently duplicates** → D6 makes upsert the only write mode used, and the generic domain tests assert that writing the same key twice leaves one row. This is the single most important invariant in the module; it is worth a review check rather than only a test.
- **Upsert is a copy-on-write merge** → writing one row rewrites the partitions it touches. Batch writes per stage; never write per row. The partition choices in D7 exist partly to keep the touched set small.
- **Every dataset operation opens a connection and attaches the catalog** → with a remote catalog and object-store warehouse that is several round trips. `describe`/`list` are not free; cache them within a run.
- **Changing a chunker's parameters re-does everything** → a new `chunker_id` means new `chunk_id`s, so every extraction over that corpus becomes outstanding work again. Intended, and the reason the chunker id is content-addressed rather than mutable, but expensive: the app should say so before submitting such a request.
- **Sensor latency is not zero** → a request sits pending until the next sensor evaluation. Acceptable for a pipeline whose stages run in minutes; the app should show `pending` honestly rather than implying the run has started.
- **A sensor that crashes mid-emit could leave a row marked `running` with no run** → the job owns the transition to `running`, not the sensor, so a request stays `pending` until a run actually starts. Requests stuck `pending` beyond a threshold are a monitoring concern, not a correctness one.
- **Duplicated ontology TTLs can drift from v1's** → mitigated by sharing the URI namespace, so drift shows up as missing classes rather than as silently incompatible vocabulary.
- **`.abi` is a submodule** → this change needs a bump to a revision carrying the DuckLake dataset backend, and it also carries the object-storage change from D11, which needs upstreaming.

## Migration Plan

There is no data migration: the new module starts with empty datasets and empty graphs, and v1 is untouched.

Deployment:
1. Bump `.abi` to a revision with the DuckLake dataset backend, and land the object-storage change from D11.
2. Add `- module: phases_v2` to the `modules` list in `config.yaml`.
3. Restart. The module ensures its datasets and registers its prompts, chunkers and models on load.
4. Enable the new app for the workspace.

The dataset service needs no configuration: it is configured by default upstream, and a deployment that wants the shared-catalog variant sets `services.dataset` accordingly — independently of this change.

Rollback: remove `- module: phases_v2` from `config.yaml` and restart. Nothing v1 depends on has changed. The datasets, the `phases/v2/*` graphs and the `phases_v2_*` collections can be dropped independently, and rebuilt from the datasets if only the projections were dropped.

## Open Questions

- Which chunking mechanisms to declare beyond the v1-compatible one (512-token windows with 128 overlap). Adding a second mechanism is a data question, not a design one — the registry already supports it.
- Whether the Composer eventually wants a union view spanning v1 and v2 graphs. Deferrable: it is a query-authoring concern, and the shared vocabulary from D9 is what would make it possible.
- What retention to apply to catalog snapshots. Every write creates one, and expiry is an operator responsibility upstream; a long ingestion run will accumulate them. This affects operations, not the design.
