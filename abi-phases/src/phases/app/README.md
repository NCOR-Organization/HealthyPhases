# Reverse search (v1)

A researcher-facing **reverse search** over extracted items: given a claim or a
set of words, find *which papers* assert it and *where* in each paper.

Two search modes, both resolving every hit back to its source paper + chunk:

- **Semantic** — vector search over `phases-doc:ExtractedItem` embeddings
  (Qdrant collection `extracted_items`, `text-embedding-3-large` @ 3072 dims).
- **Keyword** — word-presence search over `extracted_text` (case-insensitive,
  all words must be present), via SPARQL.

## How it fits together (hexagonal)

```
app/
├── models.py          # domain models = API schemas (ItemLocation, SearchHit, ...)
├── interfaces.py      # ports: ISemanticIndexPort, IKnowledgeGraphPort
├── domain.py          # SearchService — business logic (tech-agnostic)
├── factory.py         # composition root: wire adapters from the engine
├── adapters/
│   ├── secondary/
│   │   ├── VectorStoreSemanticAdapter.py        # ISemanticIndexPort  -> vector store + OpenAI
│   │   └── TripleStoreKnowledgeGraphAdapter.py  # IKnowledgeGraphPort -> SPARQL (join-on-read)
│   └── primary/
│       └── SearchAPI.py    # FastAPI router
├── contracts.py            # reusable port-contract assertions (for any adapter)
└── fakes.py                # in-memory port implementations for tests
```

The data is resolved **join-on-read**: the vector store only stores
`{extracted_item_id, text}`, so each semantic hit is enriched via SPARQL against
the KG (`ExtractedItem → extracted_from_chunk → Chunk → PDFPaperFile`). No
re-ingestion / payload migration is required.

> **Location granularity:** the KG stores paper `path` + `chunk_number` (and the
> chunk text). There are *no* page numbers or character offsets. Results show
> the paper, the chunk position, and the surrounding chunk text as context.

## Endpoints

Mounted onto the existing ABI FastAPI app via `ABIModule.api()`
(`phases/__init__.py`).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/phases/api/search/semantic` | `q`, `k`, `score_threshold`, `pipeline[]` |
| GET | `/phases/api/search/keyword` | `q`, `limit`, `pipeline[]` |
| GET | `/phases/api/pipelines` | distinct pipeline names (UI facets) |
| GET | `/phases/app/` | the single-page UI |

`pipeline` is repeatable and filters by extraction pipeline
(`causes` / `how` / `when` / `where` / `effects` / `conditional_statement` / ...).

## Running

The app is part of the `phases` module, so it comes up with the ABI API server.
Open the UI at `/phases/app/` (or hit `/phases` for a redirect to the page).
It requires `OPENAI_API_KEY` in the environment for query embeddings, and a
triple/vector store already populated by the ingestion + extraction +
embedding Dagster jobs.

## User interface

This module no longer ships a page. Its Nexus app and the `/phases/app` mount were
retired when the HealthyPhases workspace app
([`phases_v2/apps/workspace`](../../phases_v2/apps/workspace/README.md)) replaced every
app of this project. The `/phases/api/*` endpoints above are unchanged.

## Tests

```bash
uv run pytest src/phases/app
```

- `domain_test.py` / `models_test.py` — pure logic with in-memory fakes.
- `contracts.py` + `contracts_test.py` — generic port contracts; reuse the
  `assert_*` helpers to validate any new adapter.
- `TripleStoreKnowledgeGraphAdapter_test.py` — runs the real SPARQL against an
  in-memory `rdflib` dataset seeded with the canonical KG shape.
- `SearchAPI_test.py` — end-to-end through FastAPI's `TestClient`.
