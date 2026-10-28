# phases_v2 — papers → chunks → extractions

## The question this module answers

> *What is this corpus asserting, and how do I know where each claim came from?*

It reads research papers from object storage, splits them into chunks, runs prompts against each
chunk with an AI model, and records every claim it extracts alongside the exact chunk, model and
prompt version that produced it.

It runs **alongside [`phases`](../phases/)**, which is not modified and not retired; only its Nexus page
gave way to the HealthyPhases app. The two share a vocabulary (`documents.owl#`) but never a named graph, a vector collection, or a dataset.

## The one idea everything else follows from

**Datasets are the system of record.** The triple store and the vector collections are *projections*
built from them.

That inverts what `phases` does, where the triple store is both the store and the query surface. The
consequence is that the graph and the embeddings can be dropped and rebuilt from the datasets at any
time, and nothing is lost — verified by dropping the graphs, clearing the ledger, re-projecting, and
getting an identical set of triples back.

Three properties fall out of it:

- **Nothing is done twice.** Re-running a finished corpus makes no model calls and writes no rows.
- **Nothing is lost when a prompt changes.** Editing a prompt produces a new version; work done under
  the old text stays attributable to the exact text that produced it.
- **Every claim is traceable** to its chunk, its paper, the model, and the prompt version.

## How identity works

Every id is derived from content, so the same input always produces the same id. That single fact is
what makes each stage idempotent without any coordination between them — one id serves as the dataset
primary key, the local name of the RDF URI, and the Dagster run key. The vector adapter maps
collection + row id to a deterministic UUIDv5 because Qdrant requires integer or UUID point ids.
The original row id remains in vector metadata as `document_id` (alongside `chunk_id` or `item_id`)
and in the projection ledger, so retries and source lookup keep the same identity.

| Id | Derived from |
|---|---|
| `paper_id` | `sha256(file contents)` — the same PDF at two paths is one paper |
| `chunker_id` | name + version + parameters — changing a setting yields a new mechanism |
| `chunk_id` | paper + chunker + position |
| `prompt_id` | prompt name + `sha256(template text)` |
| `extraction_id` | **chunk + model + prompt** — the unit of work |
| `item_id` | extraction + position |

`extraction_id` is the important one. It defines a unit of work as *one chunk, run through one model,
with one prompt version*. Change any of the three and it is new work; change none and there is
nothing to do.

## The stages

```
ingest      object storage → papers          discover recursively, render to text
chunk       papers        → chunks           split; several mechanisms may coexist
extract     chunks        → extractions      one prompt run per chunk, per model
project     datasets      → triple store     phases/v2/* named graphs
project     datasets      → vector store     phases_v2_* collections
```

Each stage is idempotent and resumable. They run in order — Dagster infers concurrency from the
dependency graph, so the stages are explicitly chained; without that it ran them in parallel and
chunking looked for papers before ingestion had finished.

### Two mechanisms prevent duplication, and they are not interchangeable

**Upsert** stops duplicate *rows*: every dataset declares a primary key and every write is an upsert.

**A SQL anti-join** stops duplicate *work*: before extracting, the module asks which chunks have no
succeeded extraction for this model and prompt.

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

Without the query, an already-extracted chunk would still be sent to the model and would merely
overwrite its own row — having paid for the call. A failed attempt is absent from the join, so it is
retried next run.

## Datasets

Namespace `phases_v2`. Every one is keyed and written only with `mode="upsert"`.

| Dataset | One row per | Key |
|---|---|---|
| `papers` | source document | `paper_id` |
| `chunkers` | chunking mechanism version | `chunker_id` |
| `chunks` | chunk | `chunk_id` |
| `prompts` | prompt version | `prompt_id` |
| `models` | declared model | `model_id` |
| `extractions` | chunk × model × prompt | `extraction_id` |
| `extracted_items` | extracted claim | `item_id` |
| `extraction_runs` | invocation | `run_id` |
| `projections` | key already projected to a target | `target` + `key` |
| `run_requests` | requested run | `request_id` |
| `paper_collections` | collection of papers | `collection_id` |
| `paper_paths` | storage path a paper was read from | `path` |
| `source_manifests` | exact artifacts a manifest-sourced request reads | `request_id` |

`extractions` keeps the model's output twice: `response` is a queryable JSON column, `raw_response`
the verbatim text. The JSON column *rejects* unparseable output — which is exactly the case where
keeping the model's words matters most — so the split is what makes "re-parse later instead of
re-paying" true for failures as well as successes.

## Reverse search

Reverse-search results display the extraction `model_id`. The model filters list models
with extracted items in the dataset, independently of which models are currently configured
for new ingestion. Select several models to include any of them; prompt and model filters
are combined. With no models selected, all models are included.

Both `/phases_v2/api/search/semantic` and `/phases_v2/api/search/keyword` accept repeated
`model` query parameters. `/phases_v2/api/search/models` returns the available model IDs.
Semantic search embeds the query once and retrieves top matches per selected model using
vector metadata filters, then merges them by score. Existing projections already store
`model_id`, so this change does not require re-embedding.

Source-path filters include subfolders, match complete path components, and combine with
model and prompt filters. Both search endpoints accept repeated `path` parameters;
`/phases_v2/api/search/paths` lists folders and parents from papers with extracted items.
Paths combine the paper's `storage_prefix` with the directory of its `storage_key`.
The UI selects folders only, not individual papers. Unknown paths return no results.
Semantic search resolves the selected folders to existing `paper_id` vector metadata,
then combines ranked lookups per paper/model. The query is embedded once per request.
To obtain an exact count with the shared vector port, the adapter expands each ranked
lookup until all matches above the threshold have been read. This also includes points
not yet counted as indexed by Qdrant. Broad semantic queries therefore cost more than
a bounded top-k lookup; there is no silent cap on the reported total or CSV export.

Each result includes `source_path` and the stored `prompt_template` associated with its
`prompt_id`. The prompt viewer shows that historical template, keeping its chunk placeholder,
alongside the separately available source context. It never substitutes the current code template.

The app displays "Showing N of M matches" and loads subsequent batches when the user
scrolls to the bottom (with a manual **Load more** fallback). The batch-size control is
limited to 100; total matches are not. Keyword results use deterministic paper/chunk/item
ordering; native Qdrant semantic pages use exact vector scoring and Qdrant point-ID tie ordering.

`GET /keyword` accepts `limit` and `offset`; `GET /semantic` accepts `k` and `offset`.
Responses include `total` (also exposed as `count`), `page_count`, `has_more`, `next_offset`,
and the dataset `snapshot`. Clients pass that snapshot to later pages and exports to
keep keyword results and provenance consistent if ingestion adds records. Semantic filtering and ranking use the current vector index, which has no snapshot API; indexing
or metadata changes can change semantic totals/order between requests. The snapshot pins
source details, not Qdrant metadata. The existing CLI/top-k methods
remain available for bounded searches.

**Export all matches (CSV)** calls `GET /export?mode=keyword|semantic&q=...` using the
last submitted query, filters, threshold, and dataset snapshot, independently of loaded
pages or unsubmitted form edits. The server reads every matching row, spools large CSVs
to a temporary file, and only begins the download after reads succeed, so a storage
failure cannot masquerade as a successful partial export. New search requests cancel
stale page responses and pending exports. Search request validation is defined in
`app/contracts/search.proto` and generated with `make proto`.
Columns include query, mode, item ID, extracted text, score, model, prompt ID/name/template,
paper ID/name, source folder, and chunk ID/sequence/context. CSV uses UTF-8 with a BOM,
quoted multiline fields, and escaped quotes. Formula-like text is prefixed with an apostrophe
to keep spreadsheet applications from evaluating it. Empty or failed searches disable export.

## Layout

Organised by **domain**, not by ABI construct. This differs from what `abi new module` scaffolds
(`agents/ integrations/ pipelines/ workflows/`) — of those, only `ontologies/` and `orchestrations/`
appear here. If you know ABI and are looking for `workflows/`, the equivalent logic lives in each
domain's `domain.py`.

```
phases_v2/
├── identity.py             # every id derivation, in one place
├── sql.py                  # SQL literal escaping (the dataset port takes no parameters)
├── datasets/
│   ├── schemas.py          # every DatasetSpec
│   └── store.py            # the ONLY code that writes to a dataset
├── papers/                 # ─┐
├── chunking/               #  │ each: interfaces.py, domain.py, fakes.py,
├── extraction/             #  │ adapters/secondary/, factory.py, and a _test.py per file
├── projection/             #  │
├── requests/               #  │
├── search/                 # ─┘ reverse search: semantic + keyword, over extracted_items
├── paper_collections/      # collections of papers and resolving one into exact documents
├── prompts/                # templates declared in code + their text
├── playground/             # trying a prompt on a few chunks of one paper; writes nothing
├── models/                 # the models a run may use
├── ontologies/             # this module's own copy of the TTLs + the URIs it emits
├── orchestrations/         # Dagster jobs and the run-request sensor
├── app/                    # the workspace app's services and HTTP endpoints
├── assistant/              # the Assistant's actions and tools, and the guard on costly ones
├── agents/                 # WorkspaceAssistantAgent, which Nexus loads in its right pane
└── apps/
    └── workspace/          # the HealthyPhases Nexus app: index.html, css/, js/ modules, tests/
```

Each domain takes its collaborators as arguments and imports no adapter, so its tests run against
fakes. `factory.py` is the one place that knows which real implementation to hand it.

## Two invariants that are enforced, not documented

**Every write is an upsert.** `DatasetSpec.primary_key` is *advisory* upstream — the store matches
upserts against it but enforces no uniqueness, so a single stray `append` would duplicate rows with
no error. `store.write_rows` is the only code that writes, and a test walks every module file's AST
looking for `.write(` calls and `mode=` arguments. It has already caught a real violation.

**Chunk boundaries match `phases`.** `WindowChunker` is pinned against v1's own
`split_to_overlapping_chunks` across several parameter sets, so the two modules cannot silently
diverge.

## Running it

The app records a **request**; it never contacts the orchestrator. A Dagster sensor picks pending
requests up, keyed on the request id so Dagster's own run-key deduplication makes it exactly-once.
A request submitted while the orchestrator is down is picked up when it returns.

Jobs, all runnable alone from the Dagster UI:

```
phases_v2_ingest_papers      phases_v2_project_graph
phases_v2_chunk_papers       phases_v2_project_vectors
phases_v2_run_extraction     phases_v2_full_pipeline
```

### Configuration

```yaml
  - module: phases_v2
    enabled: true
    config:
      papers_root: "phases_v2"   # object-storage prefix papers are read from
      openai_api_key: "{{ secret.OPENAI_API_KEY }}"
```

`papers_root` matters: the object-storage root is shared with every other module, so scanning it
would offer their private data as a source of papers. Owning a prefix keeps them out of scope by
construction rather than by a blacklist that needs updating whenever a module is added.

The embedding key is resolved by ABI's secret service (including its `.env` adapter) and
passed explicitly to the shared embedder factory for both ingestion and semantic search.
Both use `text-embedding-3-large` at 3072 dimensions. The key is required when embedding;
keyword search does not need it. No process environment fallback is used.

Prompts, chunkers and models are declared in code, not configured — they are published to datasets
on module load so a client can list them without reading the source.

## What one paper costs

Measured on a 9-page journal article:

```
7,713 words → 20 chunks (512 tokens, 128 overlap) → 20 extractions → 107 claims
```

With every prompt selected that is 20 × 8 = 160 model calls for a single paper. Running it a second
time costs nothing: 20 skipped, zero calls, no new rows.

## Deliberately not done

- **No migration from `phases`.** This module starts empty; v1 keeps its data.
- **No union view across v1 and v2 graphs.** The shared vocabulary would make one possible.
- **Snapshot retention is an operator concern.** Every write creates a DuckLake snapshot; expiry and
  compaction are not scheduled here.


### Extraction concurrency

One ingestion request still starts one full-pipeline Dagster run. Stages and
prompts execute in order; within each prompt, a bounded thread pool overlaps
model HTTP calls. Set `modules[].config.extraction_workers` on `phases_v2`
(default `20`, positive integer; `1` for sequential requests). The existing
engine and prompt-bound model are reused. Database writes and report updates
stay on the coordinating thread, with items saved before success records.
Only a pool-sized window is submitted, so queued work and completed responses
remain bounded. Failed calls remain individually retryable on the next run.
Provider retry/timeout behavior is unchanged; lower the worker count if provider
rate limits are encountered. This setting applies to newly started execution,
not an already-running extraction process.


## Authoring pipelines in the web app

The HealthyPhases app's **Collections**, **Prompts** and **Runs** sections support the following workflow:

1. Create an input collection under the configured `papers_root`.
2. Upload PDFs into that collection (25 MiB per file). Each file reports its own
   outcome; uploads do not start extraction. Uploads use content-addressed paths,
   so retries are idempotent and different PDFs with the same filename coexist.
3. Create or duplicate a prompt, including `{chunk_text}` in the template. Select
   an existing validated output format; `results` is the generic list of claims.
   Saving changed text creates a new version. Changing only the output format
   requires changing the name or template too, preserving existing prompt IDs.
4. Choose locations, prompt versions, chunker, and model. Request a run immediately,
   or save a named configuration and use **Run saved pipeline** later.
5. Follow requests under **Runs**. The list refreshes every 10 seconds while it is open,
   and again whenever you come back to the app.

Saved configurations are immutable copies of their inputs; load one, edit the form,
and save a new configuration to make a variant. They reference exact prompt versions
but include whatever documents their locations contain when ingestion starts.
Deleting prompts, documents, and configurations is not exposed by this UI.

The `input_locations` dataset stores named prefixes, including empty collections.
The `pipelines` dataset stores named configurations and their input JSON. Both are
created at module initialization using the existing dataset service; no existing
schema migration is required. Restart the ABI API and Dagster processes after upgrading.
These catalogs share the existing module storage scope; they are not per-user workspaces.

Full pipeline runs pass the IDs of successfully ingested or already-ingested selected
papers through chunking and extraction. An empty collection remains an empty scope;
it never falls back to the whole corpus. Standalone stage jobs retain their existing
whole-corpus default. Graph and vector projections remain incremental shared projections.

New authoring endpoints require the platform's existing ABI API key or registered
Nexus session-token validation. The embedded UI sends the current Nexus session token;
a direct API client supplies `Authorization: Bearer ...`. No new authentication scheme
or inter-domain security policy is introduced. Uploads validate size, filename, path,
and PDF header; full PDF rendering happens during ingestion.

New endpoints under `/phases_v2/api`:

- `POST /prompts`: save `{name, template, output_key}` as a prompt version.
- `POST /locations`: create `{name}` beneath the configured papers root.
- `POST /documents?location=...&filename=...`: upload raw PDF bytes.
- `GET /pipelines` and `POST /pipelines`: list/save `{name, inputs}` configurations.
- `POST /pipelines/{pipeline_id}/requests`: request the saved configuration.
- `GET /papers?q=&chunker_id=&limit=&offset=`: ingested papers whose file name,
  path, PubMed title or PMID matches `q`, each with its `path` and chunk counts per
  chunker; with `chunker_id`, only papers chunked with it. Returns `{papers, total,
  limit, offset}` (`limit` up to 200). Collections picks single papers from it,
  Prompts tries a prompt on one, and Results lists them (see Results per paper for
  the other filters and fields).
- `GET /papers/{paper_id}/chunks?chunker_id=`: each chunk's `seq` and a short preview.
- `POST /prompts/try`: run a `draft` (`{name, template, output_key}`) or a saved
  `prompt_id` with `model_id` on `seqs` (or the `first` N, 1 to 10, default 3) chunks of
  `paper_id` cut with `chunker_id`, at most 10. Answers in the same request, each
  chunk with its items (relations as objects), or its error and raw output, and the
  time taken. With `baseline_prompt_id`, each chunk also carries what that version
  stored for it with the same model, or `not_run`. Model calls run four at a time
  under a 90-second deadline; chunks still running then come back `timed_out`. It
  renders and parses through `extraction.domain.attempt`, as a run does, and writes
  nothing: no prompt, extraction, item, run or projection.
- `GET /prompts/versions?name=`: every version saved under a name, newest first,
  with its text, the extraction runs and run requests that used it, and its item
  counts per model. Versions are ordered by `first_seen`, the earliest of their
  `registered_at`, first run and first request. On start, declared prompts already
  in `prompts` are not rewritten, so a built-in text keeps the time it first
  appeared and never lists above versions saved after it.

Management request shapes and validation are defined in
`app/contracts/pipeline_management.proto` and, for trying a prompt,
`app/contracts/prompt_playground.proto`. `make proto` regenerates the checked-in
Protobuf descriptors using the existing checksum-pinned Protovalidate source. Python
loads the generated descriptors and runs Protovalidate before persistence. Format
compatibility and storage-root containment are checked by the application service.

### Native Qdrant filtering and migration

New extracted-item vectors include `prompt_name`, `model_id`, `paper_id`,
`source_path`, every `source_ancestors` folder (including the folder itself), and
`search_metadata_version=1`, alongside existing item/chunk/extraction/prompt IDs.
Keyword payload indexes support the filter fields; the metadata version has an
integer index. OR selections within a facet combine with AND across facets.
Folder matching respects path-component boundaries.

With complete versioned metadata, default semantic searches use a native exact
Qdrant count plus a paged exact-scoring query. Only that page's payload and source
provenance are loaded. Query embeddings and metadata counts are reused. A score
threshold cannot be counted by the metadata count API: those searches enumerate
only IDs/scores in 1,024-point batches, applying the threshold and all filters in
Qdrant, then load payloads for the requested page. Full CSV exports use 500-result
pages and still return all matches.

Run `phases_v2_refresh_vector_metadata` in Dagster after deployment to update
existing payloads and create indexes without changing point IDs, vectors, or text.
The job reads a dataset snapshot, updates existing points in batches, and fails
explicitly if a point cannot be matched to a dataset item. It is idempotent and
can be rerun after correcting paper paths or prompt annotations. New projections
write the metadata directly. Re-run this job after editing annotations on rows
whose vectors were already projected; the embedding ledger alone does not refresh
old payloads.

Until all points carry the current metadata version, the API uses the legacy
search path (dataset filtering and exhaustive ranking). Readiness is rechecked
every 30 seconds; do not mark migration complete based only on a running job.
Non-Qdrant backends retain that path. No new persistence or dependencies are added.

Caches are process-local, capped at 32 entries / an estimated 64 MiB each, with a
five-minute TTL; identical concurrent computations are coalesced and failures are
not retained. Entries include the dataset snapshot and applicable filters.
Qdrant itself has no snapshot here, so concurrent indexing/payload changes can
shift results during paging/export. Exact scoring avoids approximate-search
variations between page sizes, but does not freeze concurrent mutations.

### Probabilistic search results and paper downloads

Reverse search detects probability-modulating JSON claims (single relations,
lists, or `relations` envelopes) and displays their participant, subject process,
and target process as typed nodes. Edges explicitly label increases, decreases,
or neutral (no effect) on the target's probability. Evidence and the original
JSON remain available; unknown or incomplete payloads retain their text.
Source chunks appear before the stored extraction prompt.

`GET /phases_v2/api/search/paper?item_id=...` downloads the original PDF resolved
from that item's paper record. The service reads the recorded object-storage
prefix/key and restricts it to the configured `papers_root`; it accepts no caller
file paths or external URLs. Missing PDFs show an inline error. Downloads use the
same access controls as search, so the configured corpus must contain only papers
intended for search users. Current semantic/keyword matching is unchanged; a
dedicated directional-effect query remains future work.

Run the focused backend and frontend checks with `make test-search`.

Older structured extractions were stored using Python dictionary/list text.
Search responses convert these literal payloads to JSON on read so existing
matches can render as graphs without re-extraction or a corpus migration.
New structured items are stored as JSON. Compatibility parsing is bounded,
uses literal-only parsing, and leaves malformed or unsupported text unchanged.

Keyword queries support double-quoted exact words and phrases: `"like"` excludes
`likely` and `dislike`; `"being alone" stress` requires that phrase plus `stress`.
Matching is case-insensitive, quoted words use word boundaries, and spaces or
line breaks between phrase words are equivalent. Straight and smart double
quotes work. Unquoted terms retain substring matching, all terms are required,
and an unclosed quote falls back to ordinary word matching. These rules apply
to result counts, pagination, highlighting, and complete CSV exports.

### Structured probability-modulating relations

The `probabilistic_relations` dataset is a typed, rebuildable projection of
successful extractions whose prompt output key is `relations`. It includes
subject process, participant, target process, direction, evidence, and all source
IDs. `relation_id` is stable per extracted item and relation index. Its row
contract is `projection/contracts/probabilistic.proto`. Saved evidence is retained
in full, including legacy excerpts longer than the extraction prompt requested.

The Effects search tab queries these fields directly. Put `stress` in Target
process and choose Increases to find relationships increasing stress, regardless
of which other fields mention stress. Subject and participant filters, existing
source/model/prompt filters, pagination, and CSV export are supported. Blank
filters browse all projected relationships. Targets use text matching (including
quoted exact phrases), not ontology entity normalization.

`phases_v2_backfill_probabilistic_relations` is a standalone Dagster job for this
projection. The full pipeline and standalone extraction job also run it after
extraction. To backfill without model calls from the ABI project directory:

```sh
uv run abi run script src/phases_v2/projection/probabilistic_backfill.py -- --dry-run
uv run abi run script src/phases_v2/projection/probabilistic_backfill.py
```

Each run pins one snapshot and pages through outstanding items in batches of 500.
Derived rows are upserted before the projection ledger is recorded, so retries
cannot create duplicate relation IDs. Invalid payloads are reported (counts and
up to 20 item IDs/errors), left untouched, and retried by later runs. The backfill
never rewrites source extractions or calls an LLM. API startup only creates the
empty dataset; it does not run a potentially large backfill during startup.

## HealthyPhases workspace app

`apps/workspace/` is the one Nexus app of this project. It replaced the Phases Pipeline,
Phases V2 Reverse Search, PubMed Library and OpenAlex enrichment apps, and the v1 Reverse
Search app; their HTTP APIs are unchanged. Its sections, in the left navigation:

- **Overview**: the workflow in four steps (collect papers, prepare prompts, run, explore
  results) with live counts and links into each section.
- **Library**: PubMed search and ingestion, the paper library with its OpenAlex filters,
  downloads (ingestion requests and full ingestions), scheduled searches and OpenAlex
  enrichment. See [`../pubmed/README.md`](../pubmed/README.md) and
  [`../openalex/README.md`](../openalex/README.md).
- **Collections**: sets of papers gathered four ways, on one screen: PDFs uploaded into
  the collection, saved PubMed searches, storage folders (with their subfolders) and
  single papers picked from the library. A collection's page lists its members with how
  many papers each brings, and the papers themselves, each once, marked not ingested yet,
  ingested, or with results. Rename it, describe it, remove members, archive it, run the
  pipeline on it or search within it. Archiving and removing ask first and delete nothing.
  Library rows with a downloaded PDF, and whole saved searches, have **Add to collection**.
  Storage folders can still be created and uploaded into from this page.
- **Prompts**: browse full prompt text, create prompts, and save edits as
  new versions. Prompt text must contain `{chunk_text}` and use one of the supported
  extraction output schemas. Old versions remain selectable and resolvable by workers.
- **Runs**: **New run** selects a collection, storage folders or a PubMed search,
  previews documents, saves the selected folders as a collection, chooses prompt versions,
  and queues a run; saved pipeline configurations can be saved, loaded, and run here.
  **Requests** filters the latest 100 requests by status and opens one to inspect
  timestamps, sources, all selected prompts, execution IDs, counts, and errors. The list
  refreshes every 10 seconds while it is visible.
- **Search**: semantic, keyword and effects search over extracted items (see
  [Reverse search](#reverse-search)), optionally limited to one collection.

Every section has a deep link (`#/runs/<request_id>`, `#/search?q=...&mode=keyword`,
`#/library/schedules`, ...), and the last route comes back when Nexus reloads the app.
The open section re-reads its data whenever the app becomes visible or regains focus, so
changes made elsewhere appear. There is no build step: `index.html` loads ES modules from
`js/` through relative imports, which Nexus serves next to it under
`/app-html/phases_v2/workspace/`. [`apps/workspace/README.md`](apps/workspace/README.md)
describes the files.

### Collections of papers

A collection is a name, a description and a list of members (`paper_collections`):

- `folder`: a storage prefix under `papers_root`, including its subfolders. PDFs uploaded
  into a collection (`POST /phases_v2/api/collections/<id>/documents`) are stored under
  `<papers_root>/collections/<id>/`, which joins the collection as a folder member.
- `pubmed_query`: a saved PubMed search. It is live: every use reads the search's
  currently published PDFs, so newly downloaded papers join without any change.
- `paper`: an ingested paper (`paper_id`) or a PubMed paper with a downloaded PDF (`pmid`).

`paper_collections.domain.resolve` is the one function that turns a collection into the
exact documents it holds, one per distinct content: a known checksum is the paper's
identity, so the same PDF through two members, or at two paths, counts once. Folder
documents nobody has read yet have no checksum; an upload's is in its key (a 64-hex
folder holding that one file), and anything read before is matched by path. Ingestion
records every path it reads in `paper_paths`, the copies it skips as already known
included, because `papers` keeps only the first path of each paper: after one run, a
copy elsewhere is recognised as that paper, with its status and its search results. The collection page, run submission and search
scoping all call it. A member that cannot be read is reported on the page; a run or a
search on that collection is refused rather than covering part of it.

Collections first stored in `input_collections` (storage folders only) still list, edit
and run: each is read as a collection of folder members, and its first edit writes it to
`paper_collections` under the same id, which takes precedence from then on. The old
table is never altered, so no dataset needs to be dropped or recreated; restart the ABI
API and Dagster processes and startup creates `paper_collections`. Edits are
last-write-wins.

Endpoints, under `/phases_v2/api/collections`: list with member and paper counts
(`?counts=false` skips resolving every collection; the app asks for counts on its first
visit only), create, read one with its members and resolved
papers, update the name and description, add members, remove a member
(`DELETE .../members/<member_id>`), archive (`DELETE`) and upload PDFs into it.
`GET /phases_v2/api/papers?q=` finds ingested papers to pick.

A run on a collection (`POST /phases_v2/api/requests` or a saved configuration with
`collection_id` instead of `locations`) resolves it, writes the artifacts to
`source_manifests` and only then records the request with the location
`dataset:collection:<collection_id>`. Ingestion reads exactly those artifacts, verifying
each known checksum, so later changes to the collection never change a submitted run.
An empty collection cannot be run. Runs show the collection's name, even once archived.

Search endpoints accept `collection=<collection_id>`. It resolves to the collection's
ingested paper ids and combines with the other filters: keyword and effects search filter
in SQL, semantic search goes through the per-paper vector metadata filter. A collection
with no ingested papers finds nothing.
Prompts continue using the existing `prompts` dataset and content-based identities.
Changing an output schema requires a changed name or text to preserve that identity.

Location selection scopes ingestion, chunking, and extraction to the selected
documents, preserving the current orchestrator behavior.

Collection commands and manifests are defined in
`app/contracts/app_resources.proto` and validated server-side with Protovalidate;
run inputs and search queries in `pipeline_management.proto` and `search.proto`.
The checked-in descriptors are packaged with the module. `make proto` regenerates them
using the existing extraction descriptor's pinned validation dependency. Resource
endpoints inherit the ABI API's existing access controls; no separate role model
is introduced.

Run backend and browser-logic regressions with `make test` (or run
`uv run pytest src/phases_v2/app` and `make test-app` individually).

## Results per paper

The app's **Results** section lists every ingested paper and opens one paper with
everything extracted from it. Both read the datasets directly, so results show as soon
as a run writes them, with no projection needed.

`GET /phases_v2/api/papers` takes, besides `q` and `chunker_id`:

- `collection=<collection_id>`: the papers the collection holds now;
- `request_id=<request_id>`: the papers that run request covered: those in its
  manifest (by hash or path), those under its folders found before it finished, and
  those it wrote extractions for;
- `prompt=<name>`, `prompt_id=<version>` and `model=<model_id>` (repeatable): papers
  these ran on, with each row's counts covering those runs only;
- `has_results=true|false`: papers with at least one extracted item, or none;
- `paper_id=` (repeatable, up to 200): only those papers, which is how the Library
  learns which of its PDFs are ingested;
- `sort=title|newest|oldest`. Every order ends on the paper id, so pages are stable.

Each row adds `title` (the PubMed title when the PDF is a published PubMed artifact
with the same `content_sha256`, else the file name), `pmid`, `source` (`pubmed` or
`file`), `extractions` (`succeeded` and `failed` chunks) and `items` (count per prompt
name) with their total `item_count`. A page costs three queries whatever its size: the
filtered, sorted page with its total, and one query for every count on it. The PubMed
title comes from a join on `pubmed.artifacts` and `pubmed.papers`, made only when those
tables exist.

`GET /phases_v2/api/papers/{paper_id}` returns:

- `paper`: title, file, path, every other path it was read from, size, ingestion time;
- `pubmed`: the PubMed record (authors, journal, date, DOI, PMCID) when it has a PMID;
- `openalex`: the enrichment and its matched work, when OpenAlex has one;
- `chunkers`: chunk counts per chunker;
- `ran`: one summary per prompt version × model run on it, with succeeded and failed
  chunks, item and relation counts, and the requests whose runs wrote them;
- `requests`: every run request that covered the paper (same rules as `request_id`);
- `results`: per prompt version × model, its items in reading order (each with its
  chunk id and position, and its probability relations), and its failed chunks with
  their error and the start of what the model returned;
- `chunks`: the text of every chunk those results refer to, once.

`GET /phases_v2/api/papers/{paper_id}/export?prompt_id=&model_id=` writes the paper's
results as CSV with the search export's columns (`mode` is `paper`): one row per item,
or one per relation for items that carry relations. `prompt_id` keeps one version and
`model_id` one model; `model_id=` (empty) keeps the results whose model is unknown,
and leaving it out keeps every model. It reads only the results, not the paper's
records or runs. `GET /phases_v2/api/search/paper?paper_id=` downloads the paper's
own PDF through the same path checks as a search hit's download (`item_id=`).

The list filters and the export are validated by `app/contracts/paper_results.proto`.

On production data (269 papers, 6,113 chunks, 54,791 extractions, 106,458 items),
read-only, a page of the list took 0.3 to 0.7 s (median per filter, including a run's
papers), a median paper's page 0.55 s and the largest one (2,666 items in 18 version ×
model groups, 1.4 MB) 0.8 s. Most of that is the fixed cost of each DuckLake read.


## The Assistant

With the HealthyPhases app open, the Nexus right pane loads `WorkspaceAssistantAgent`
(`agents/`): the app's manifest declares `"agent": "phases_v2 WorkspaceAssistantAgent"`,
and the workspace lists it under `agents:` in `config.yaml`, since Nexus binds the pane
only to an agent the workspace runs. It is the same for owners and members. Users open
the pane with its button at the top right of Nexus, or ⌘K / Ctrl+K once focus is outside
the app; the app's sidebar and Overview say so, with example requests.

The pane gets no message from the app, so the Assistant does not know the section or
item on screen. Its instructions describe each section, the workflow and the names of
the buttons, and tell it to look things up or ask.

Its tools (`assistant/tools.py`) are thin wrappers (`assistant/workspace.py`) over the
same services the endpoints use: `PipelineAppService` and its collections, prompt
versions, playground, papers and results, the search service, and the PubMed and OpenAlex
services when those modules are loaded. It never calls the HTTP API.

- **Reads** collections with their members and papers, saved PubMed searches and the
  library, prompts and versions, models and chunkers, runs and their counts, PubMed
  downloads, schedules and enrichments, saved configurations, papers and a paper's
  results, and searches findings by meaning or keyword.
- **Acts freely**: searches PubMed (saving the search), creates a collection, renames or
  describes it, adds members, saves a prompt version, tries a prompt (at most 10 chunks,
  writing nothing) and saves a run configuration.
- **Acts after a yes**: queuing a run on a collection, downloading a PubMed search's
  papers (previewed ones, or all it matches as a full ingestion), creating a PubMed
  schedule and queuing OpenAlex enrichment. Each is a `prepare_*` tool, which checks what
  queuing would check and returns a plain summary with a token, and a `queue_*` or
  `create_*` tool, which needs that token with the same parameters.
- **Never** deletes, archives, removes a member or turns a schedule off: no tool does.
  It has only these tools; the default agent tools (files, commands) are off.

`assistant/confirmations.py` enforces the yes. A token is single-use, expires after ten
minutes, and is bound to the action, a digest of its parameters, the conversation and
the user (from what Nexus sets on the request: `agent_chat_id`, `agent_user_email`).
Preparing the same action again in a conversation replaces the earlier token, so a
summary the user turned down cannot be executed afterwards. A token is refused in the
turn that prepared it: the agent records the latest user message around its tool calls
(`WorkspaceAssistantAgent.call_tools`), so the user must have written since. Where what an
action covers can change after it was prepared, the token is also bound to it: a run to
the exact papers the collection resolved to (`PipelineAppService.collection_run_scope`,
also used to submit that same resolution), a previewed download to its PMIDs (passed to
the publisher by name), an enrichment to its paper count. If that changed, the action is
prepared again. Tokens live in the API process, which is a single one; a restart only
means preparing again. A queued run records the user as `requested_by`; PubMed downloads,
schedules and OpenAlex requests have no such field.

Nexus builds every agent when it starts, and one failing stops the rest loading, so the
Assistant builds its services (`assistant/factory.py`) on first use: a store or module
that cannot be reached makes the tools that need it answer that it is unavailable, and
the next call tries again.

## Published PubMed sources

**Runs → New run** offers **Storage folders** and **PubMed search** sources.
Choose a saved PubMed search to preview its successfully published PDF artifacts,
then select chunker, prompt versions and model and click **Request run**.
Each query option includes its distinct published-paper count and last completed
ingestion date in the browser's local timezone. Multiple PDF versions count as one
paper. The date is the latest successful or partially successful PubMed publication
request for that query, including runs that reused PDFs. Pending or failed requests
do not advance it; queries without such a completed request show "No completed
ingestion". Refreshing queries preserves the selected query.
The source is the public contract version 1 in the `pubmed` dataset namespace;
Phase v2 has no Python dependency on the publisher implementation.

The `source_manifests` dataset stores the exact object keys and SHA-256 checksums
for each PubMed request before its `run_requests` row becomes pending. Query
membership changing later cannot expand an existing request. The `sources/`
package owns publication discovery, manifest recording and checksum verification.
All stages in a full run are scoped to its selected papers, including already
ingested papers that still have outstanding extraction work. Missing or altered
artifacts fail the run; they cannot cause a fallback to a broad prefix scan.

Publication does not schedule a Phase v2 run. Scheduled pipelines and automatic
new-paper ingestion are a later phase. Existing object-storage collections remain
available, with their own configured root; PubMed access is through its explicit
published dataset, not by relaxing the collection root restriction.

PubMed requests carry a `dataset:pubmed:<query_id>` source marker, and collection
requests `dataset:collection:<collection_id>`. Any `dataset:` request whose manifest is
missing fails instead of treating the source as a prefix.
