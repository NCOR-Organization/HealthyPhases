## Why

The current `src/phases` pipeline writes papers, chunks and extractions directly into the triple store, keeps its prompts as loose `.txt` files on disk, and tracks "already done" work in a filesystem cache keyed on path fingerprints. That makes the triple store both the system of record and the query surface, so nothing is browsable or SQL-queryable, prompt changes silently overwrite provenance, and there is no ledger that answers "has this chunk been extracted with this model and this prompt?" without re-deriving it from triples.

The ABI platform now provides a dataset service (`engine.services.dataset`), a model registry, and an apps system that the Nexus UI already surfaces. Since the DuckLake backend landed upstream, that dataset service also offers keyed upsert, a native JSON column type, and catalog-wide coherent snapshots — which is what makes a dataset-backed pipeline honest rather than approximate. A new module built on those makes the pipeline inspectable and re-runnable, and lets the graph and the vector collections become *projections* of durable datasets rather than the only place the work exists.

## What Changes

- **New module `src/phases_v2`**, added alongside `src/phases`. The existing module is **not** modified and **not** retired — both load and run permanently.
- **Datasets become the system of record** for the pipeline, in the `phases_v2` namespace: `papers`, `chunkers`, `chunks`, `prompts`, `models`, `extraction_runs`, `extractions`, `extracted_items`, `projections`, `run_requests`. Every row is keyed by a content-addressed id and written with `mode="upsert"`, so re-running any stage is idempotent.
- **Recursive paper ingestion from object storage.** A caller selects one or more object-storage locations; the module walks them recursively and records every discovered paper in the `papers` dataset, keyed by content hash.
- **Prompt templates defined in code, versioned by hash.** On module start the module registers its templates into the `prompts` dataset. Changing a template's text produces a new `prompt_id`; prior rows and everything extracted with them are preserved.
- **AI models declared in code** via the ABI model registry and mirrored into the `models` dataset so the webapp can list them.
- **Pluggable chunking.** A chunk references both its paper and the chunker that produced it, so multiple chunking mechanisms can coexist over the same corpus.
- **Extraction deduplicated on `chunk × model × prompt`.** Before running, the module diffs the candidate set against the `extractions` dataset and only executes what is missing. Model output is kept verbatim in a JSON column and exploded into per-item rows.
- **Graph projection into separate named graphs** (`phases/v2/...`), so the two modules never write the same triples. Re-runnable and keyed on `extraction_id`.
- **Vector projection** into collections for chunks and for extracted sentences, so the search app can query both.
- **Projectors read at a pinned snapshot.** Because snapshots are catalog-wide and coherent, a projection run reads `chunks`, `extractions` and `extracted_items` at one instant rather than racing a concurrent writer.
- **A new app** under `src/phases_v2/apps/` that lets a user pick storage locations, chunker, prompt and model, and **records a run request** that a Dagster sensor detects and turns into a run. The app never contacts the orchestrator directly.
- **Recursive listing added to the core object-storage port** in the `.abi` submodule. `list_objects` is depth-1 only today (S3/R2 pass `Delimiter="/"`, FS uses `os.listdir`), so recursive discovery has no supported primitive.

## Capabilities

### New Capabilities

- `object-storage/recursive-listing`: A recursive object listing primitive on the object-storage port, implemented by every secondary adapter and covered by shared adapter tests.
- `phases-v2/paper-ingestion`: Discovering papers under selected object-storage locations and recording them in a content-addressed `papers` dataset.
- `phases-v2/chunking`: A registry of chunking mechanisms and a `chunks` dataset where every chunk references its paper and its chunker.
- `phases-v2/prompt-registry`: Code-defined prompt templates persisted to a `prompts` dataset, versioned by content hash so prior versions are never lost.
- `phases-v2/model-catalog`: Code-defined AI models registered with the ABI model registry and mirrored to a `models` dataset for the webapp.
- `phases-v2/extraction`: Deduplicated extraction over `chunk × model × prompt`, with results and per-item rows persisted to datasets.
- `phases-v2/graph-projection`: Idempotent projection of the extraction datasets into dedicated named graphs in the triple store.
- `phases-v2/vector-projection`: Idempotent projection of chunks and extracted items into vector collections.
- `phases-v2/pipeline-app`: A Nexus app that presents the pipeline inputs and records run requests for the orchestrator to pick up.

### Modified Capabilities

None. `openspec/specs/` is currently empty, and this change does not alter the behavior of `src/phases`.

## Impact

**New code**
- `src/phases_v2/` — a self-contained module: domain, ports, primary and secondary adapters, factories, and per-file `_test.py` companions.
- `src/phases_v2/apps/<app>/` — `manifest.json` + UI, following the pattern of `src/phases/apps/reverse_search`.

**Modified code (`.abi` submodule — needs upstreaming)**
- `naas_abi_core/services/object_storage/ObjectStoragePort.py` — new recursive listing method on `IObjectStorageAdapter` and `IObjectStorageDomain`.
- `ObjectStorageSecondaryAdapterFS.py`, `...S3.py`, `...R2.py`, `...Naas.py` — implementations.
- `ObjectStorageService.py` — facade passthrough.

**Upstream dependency (not in this change's scope)**
- The DuckLake dataset backend in `naas-abi-core` — keyed upsert via `DatasetSpec.primary_key`, the `json` column type, and catalog-wide integer snapshots. This change consumes those; it does not implement them. It requires an `.abi` bump to a revision that includes them.

**Platform surfaces used**
- `engine.services.dataset` (`DatasetService`) — must be added to `phases_v2`'s `ModuleDependencies.services`. The service is configured by default upstream, so no deployment change is needed to make it available.
- `engine.services.object_storage`, `triple_store`, `vector_store`, and the model registry.
- Dagster: new `DagsterOrchestration` definitions, including a sensor that turns pending `run_requests` rows into runs.

**Constraints inherited from the platform**
- `DatasetSpec.primary_key` is **advisory** — the store does not enforce uniqueness, it only uses the key to match an upsert. An `append` into a keyed dataset still creates duplicates, so every keyed dataset in this module must be written with `mode="upsert"`.
- Snapshots are catalog-wide: any write to any dataset advances the counter. The optional write-time `snapshot_id` is therefore a whole-catalog compare-and-swap token, unsuited to fine-grained concurrency. This module relies on idempotent upserts and adapter retries instead.
- Dataset, namespace and column names must match `^[A-Za-z][A-Za-z0-9_]*$`.
- The Nexus datasets API is read-only, so it can browse the pipeline's datasets but cannot trigger runs.

**Not affected**
- `src/phases` and its graphs, workflows, agents, ontologies, and the `reverse_search` app. No migration of existing data is in scope.
