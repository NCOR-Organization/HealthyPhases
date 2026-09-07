## 1. Core: recursive object listing (`.abi` submodule)

- [x] 1.1 Bump `.abi` to a revision carrying the DuckLake dataset backend; verify `engine.services.dataset_available()` is `True` and that `DatasetSpec` accepts `primary_key` and a `json` column
- [x] 1.2 Write the shared conformance suite `services/object_storage/tests/object_storage__secondary_adapter__generic_test.py` covering nested depth, no directory entries, empty prefix, missing prefix and multi-page results; verify it fails against every adapter for want of the method
- [x] 1.3 Add `list_objects_recursive(prefix, queue=None)` to `IObjectStorageAdapter` and `IObjectStorageDomain` in `ObjectStoragePort.py`; verify `mypy` reports every adapter as missing the abstract method
- [x] 1.4 Implement it in `ObjectStorageSecondaryAdapterFS` with a filesystem walk; verify the conformance suite passes for FS
- [x] 1.5 Implement it in `ObjectStorageSecondaryAdapterS3` by dropping `Delimiter` and paginating; verify the conformance suite passes against the S3 adapter's existing test fixture
- [x] 1.6 Confirm `ObjectStorageSecondaryAdapterR2` inherits the S3 implementation unchanged, and add the delegating override to `ObjectStorageSecondaryAdapterNaas`; verify both stay instantiable and that neither gains a test reaching a live service
- [x] 1.7 Add the passthrough to `ObjectStorageService`; verify `ObjectStorageService_test.py` covers it and that existing `list_objects` tests still pass unchanged
- [x] 1.8 Run the full `.abi` test suite and `mypy`; verify no regression, then commit the submodule and bump the pointer in the parent repo

## 2. Module skeleton and dataset schemas

- [x] 2.1 Create `src/phases_v2/` with `__init__.py` declaring `ABIModule(BaseModule)` and `ModuleDependencies(services=[ObjectStorageService, DatasetService, TripleStoreService, VectorStoreService])`; verify the engine loads the module with `- module: phases_v2` added to `config.yaml`
- [x] 2.2 Write `schemas_test.py` asserting every dataset name, column name and namespace satisfies `IDENTIFIER_PATTERN`, and that every dataset declares a non-empty `primary_key`; verify it fails with no schemas defined
- [x] 2.3 Define the ten `DatasetSpec`s from design.md D2 with the primary keys and partitions given there; verify `schemas_test.py` passes
- [x] 2.4 Implement idempotent `ensure_datasets()` that creates only what is missing; verify a test calling it twice creates each dataset once and raises nothing the second time
- [x] 2.5 Implement the id derivations from design.md D3 in one `identity.py`; verify `identity_test.py` covers determinism and that any changed input yields a different id
- [x] 2.6 Implement a single `write_rows()` helper that always uses `mode="upsert"` and is the only place the module calls `dataset.write`; verify a test asserts no other module file references `mode=` or calls `dataset.write` directly
- [x] 2.7 Wire `ensure_datasets()` into module load, guarded on `dataset_available()`; verify a test with the dataset service absent logs and returns without raising

## 3. Registries: prompts, chunkers, models

- [x] 3.1 Write `prompts/domain_test.py` for the prompt-registry spec — registration on start, new `prompt_id` on edited text, exactly one row per version after a restart, and rejection of a template missing its chunk placeholder; verify it fails
- [x] 3.2 Implement the prompt registry domain against a fake dataset port; verify `prompts/domain_test.py` passes
- [x] 3.3 Port the existing prompt texts from `src/phases/workflows/*/prompts/*.txt` into code declarations under `src/phases_v2/prompts/`; verify each declared template's hash is stable across two module loads
- [x] 3.4 Write `chunking/registry_test.py` for the chunkers spec — registration, new `chunker_id` on changed params, one row per mechanism after a restart; verify it fails, then implement until it passes
- [x] 3.5 Declare the v1-compatible chunker (512-token windows, 128 overlap) and register it; verify its `chunker_id` is stable and `chunkers` holds exactly one row for it
- [x] 3.6 Write `models/catalog_test.py` for the model-catalog spec — declared models are available, an undeclared model id is rejected before any row is written, one row per model after a restart; verify it fails, then implement against the ABI model registry until it passes
- [x] 3.7 Wire all three registries into module load; verify a test loading the module twice leaves exactly one row per declared prompt, chunker and model, and that neither load issues a read before writing

## 4. Paper ingestion

- [x] 4.1 Write `papers/domain_test.py` for the paper-ingestion spec — recursive discovery, multiple locations, a missing location failing without aborting the run, content-addressed identity, the same content at two paths collapsing to one `paper_id`, and resumability; verify it fails
- [x] 4.2 Define `papers/interfaces.py` with the ports the domain needs (object listing/reading, text rendering, dataset writes); verify `mypy` is clean and the domain imports no adapter
- [x] 4.3 Implement `papers/domain.py` against fakes; verify `papers/domain_test.py` passes with no real object storage or PDF library involved
- [x] 4.4 Write the generic secondary-adapter test suite for the text-rendering port; verify it fails with no adapter
- [x] 4.5 Implement the PDF text-rendering secondary adapter; verify it passes the generic suite
- [x] 4.6 Implement `papers/factory.py` wiring the domain from `engine`; verify an integration test ingests a small fixture tree from the FS object-storage adapter and lands the expected rows in `papers`
- [x] 4.7 Verify re-running ingestion over the same fixture tree leaves the row count unchanged and re-renders no text

## 5. Chunking

- [x] 5.1 Write `chunking/domain_test.py` for the chunking spec — chunks reference paper and chunker, two mechanisms coexist over one paper, re-running leaves the rows unchanged, and a run can be scoped to a subset of papers; verify it fails
- [x] 5.2 Implement `chunking/domain.py` against fakes; verify `chunking/domain_test.py` passes
- [x] 5.3 Implement the v1-compatible chunker as a secondary adapter behind the chunker port; verify it produces the same chunk boundaries as `phases.utils.split_to_overlapping_chunks` for a fixture text
- [x] 5.4 Implement `chunking/factory.py`; verify an integration test chunks the ingested fixture papers and lands rows in `chunks` partitioned by `chunker_id`

## 6. Extraction

- [x] 6.1 Write `extraction/dedup_test.py` for the identity and dedup requirements — same inputs give the same `extraction_id`, any differing input gives a different one, nothing-to-do runs make no model calls, an edited prompt makes every combination outstanding again, new papers make only their chunks outstanding, and a failed row is retried; verify it fails
- [x] 6.2 Implement the outstanding-work query from design.md D4 behind a port; verify `extraction/dedup_test.py` passes against a real dataset service with seeded rows
- [x] 6.3 Write `extraction/domain_test.py` for the results requirements — success rows, failure rows carrying the reason, one failure not aborting the run, one row per item, a zero-item success, and re-recording the same `extraction_id` leaving one row; verify it fails
- [x] 6.4 Implement `extraction/domain.py` against a fake model port, writing `extracted_items` before the `extractions` row per design.md D6; verify `extraction/domain_test.py` passes
- [x] 6.5 Store the model response in the `json` column; verify a test queries `extractions` for responses with more than N items using SQL alone, without parsing in the caller
- [x] 6.6 Implement the LLM secondary adapter behind the model port; verify it passes the generic adapter suite with a stubbed transport
- [x] 6.7 Implement `extraction_runs` recording — scope, timings and succeeded/failed/skipped counts; verify a test asserts the counts match what the run actually did
- [x] 6.8 Implement run scoping (model, prompt, chunker, optional paper subset, optional max chunks); verify a scoped test run executes at most the requested number of outstanding units

## 7. Graph projection

- [x] 7.1 Copy the ontology TTLs into `src/phases_v2/ontologies/`, generate the Python classes once and commit them; verify the module loads without regenerating anything and that class URIs match v1's `documents.owl#` namespace
- [x] 7.2 Write `projection/graph_test.py` for the graph-projection spec — writes only to `phases/v2/*` graphs, never touches v1's graphs, is rebuildable from datasets, does not duplicate on re-run, projects only new rows, resumes after interruption, and preserves chunk/model/prompt provenance; verify it fails
- [x] 7.3 Implement `projection/graph.py` against a fake triple-store port using the `projections` ledger; verify `projection/graph_test.py` passes
- [x] 7.4 Pin the run to one snapshot: take the current `snapshot_id` once and read every dataset at it; verify a test that writes new extractions mid-run projects only the starting state, and never sees an extraction without its items
- [x] 7.5 Verify against a real Oxigraph instance that clearing the `phases/v2/*` graphs and re-projecting yields an equivalent graph, and that v1's graphs are byte-identical before and after

## 8. Vector projection

- [x] 8.1 Write `projection/vectors_test.py` for the vector-projection spec — dedicated collections, v1's collections untouched, resolvable provenance in metadata, no re-embedding on an unchanged re-run, only-new-items on an incremental run, resumption after interruption, and a snapshot-pinned run ignoring rows written mid-run; verify it fails
- [x] 8.2 Implement `projection/vectors.py` writing `phases_v2_chunks` and `phases_v2_extracted_items` with deterministic vector ids and `text-embedding-3-large` at 3072 dimensions, reading at one pinned snapshot; verify `projection/vectors_test.py` passes against a fake vector-store port
- [x] 8.3 Verify against the configured sqlite-vec store that a second run computes zero embeddings and leaves `count_vectors` unchanged

## 9. Run requests and orchestration

- [x] 9.1 Write `requests/domain_test.py` for the request requirements — a submitted request is recorded pending with its inputs and returns its `request_id`, a request is recorded even when the orchestrator is down, and a failure to record is reported rather than claimed as success; verify it fails
- [x] 9.2 Implement `requests/domain.py` and its lifecycle transitions (`pending` → `running` → `succeeded`/`failed`) against a fake dataset port; verify `requests/domain_test.py` passes
- [x] 9.3 Implement `orchestrations/PhasesV2Orchestration.py` as a `DagsterOrchestration` exposing `ingest_papers`, `chunk_papers`, `run_extraction`, `project_graph` and `project_vectors`; verify `dagster definitions validate` lists all five alongside v1's existing definitions
- [x] 9.4 Add the `full_pipeline` job chaining the five in order; verify an end-to-end run over the fixture corpus produces rows in every dataset and triples in the v2 graphs
- [x] 9.5 Implement the sensor that emits `RunRequest(run_key=request_id)` for each pending request, following the pattern at `XSearchRecentTweetsFilesOrchestration.py:446`; verify a test with two pending requests yields two run requests with distinct run keys
- [x] 9.6 Verify the sensor observing the same pending request twice before its run starts produces only one run, and that the job — not the sensor — owns the transition to `running`
- [x] 9.7 Verify a run that fails marks its request `failed` with the reason and is not silently retried
- [x] 9.8 Define the run config schema carrying locations, chunker, prompt and model; verify a request naming an undeclared model fails before any dataset write

## 10. Pipeline app

- [x] 10.1 Implement the module's `api()` endpoints — list prompts, list models, list chunkers, browse storage locations, submit a request, read request status; verify each endpoint's test passes and that a wiring error does not break engine boot
- [x] 10.2 Write `src/phases_v2/apps/<app>/manifest.json` following `src/phases/apps/reverse_search/manifest.json`; verify the app appears in the workspace apps listing and can be enabled
- [x] 10.3 Build the app UI — storage location picker, chunker/prompt/model choosers populated from the endpoints, submit button, and a request list showing pending/running/succeeded/failed; verify submitting from the UI records a request that the sensor picks up
- [x] 10.4 Verify the app refuses to submit with a missing required input and names which one
- [x] 10.5 Verify a completed request shows succeeded/failed/skipped counts matching `extraction_runs`
- [x] 10.6 Warn in the UI when the selected chunker differs from the one the corpus was last chunked with, since that makes every extraction outstanding again (design.md Risks); verify the warning appears only for that case

## 11. Verification

- [x] 11.1 Run the full parent-repo test suite and `mypy`; verify no failures and no new type errors
- [x] 11.2 Verify `src/phases` is unmodified (`git diff --stat -- src/phases` is empty) and that its `reverse_search` app, graphs and collections still work
- [x] 11.3 Run the full pipeline twice end to end over the fixture corpus; verify the second run makes zero model calls, computes zero embeddings, adds no triples, and leaves every dataset's row count unchanged
- [x] 11.4 Edit one prompt template, re-run, and verify a new `prompt_id` appears, the prior extractions remain intact and attributable, and only the new combination is executed
- [x] 11.5 Verify the module never writes with `mode="append"` — grep the module for `dataset.write` and confirm `write_rows()` from 2.6 is the only caller
- [ ] 11.6 Update `openspec/specs/` via the sync workflow and archive the change
