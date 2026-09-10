# phases_v2 — papers → chunks → extractions

## The question this module answers

> *What is this corpus asserting, and how do I know where each claim came from?*

It reads research papers from object storage, splits them into chunks, runs prompts against each
chunk with an AI model, and records every claim it extracts alongside the exact chunk, model and
prompt version that produced it.

It runs **alongside [`phases`](../phases/)**, which is not modified and not retired. The two share a
vocabulary (`documents.owl#`) but never a named graph, a vector collection, or a dataset.

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

`extractions` keeps the model's output twice: `response` is a queryable JSON column, `raw_response`
the verbatim text. The JSON column *rejects* unparseable output — which is exactly the case where
keeping the model's words matters most — so the split is what makes "re-parse later instead of
re-paying" true for failures as well as successes.

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
│   ├── schemas.py          # the ten DatasetSpecs
│   └── store.py            # the ONLY code that writes to a dataset
├── papers/                 # ─┐
├── chunking/               #  │ each: interfaces.py, domain.py, fakes.py,
├── extraction/             #  │ adapters/secondary/, factory.py, and a _test.py per file
├── projection/             #  │
├── requests/               #  │
├── search/                 # ─┘ reverse search: semantic + keyword, over extracted_items
├── prompts/                # templates declared in code + their text
├── models/                 # the AI models a run may use
├── ontologies/             # this module's own copy of the TTLs + the URIs it emits
├── orchestrations/         # Dagster jobs and the run-request sensor
├── app/                    # the pipeline and reverse-search apps' services and HTTP endpoints
└── apps/
    ├── pipeline/           # manifest.json + the page itself
    └── reverse_search/     # manifest.json + the page itself
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
