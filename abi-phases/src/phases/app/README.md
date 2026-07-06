# Reverse Search app

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
│       └── SearchAPI.py    # FastAPI router + static UI mount
├── frontend/index.html     # zero-build single-page UI
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
(`causes` / `how` / `when` / `where` / `effects` / `logical_sentences` / ...).

## Running

The app is part of the `phases` module, so it comes up with the ABI API server.
Open the UI at `/phases/app/` (or hit `/phases` for a redirect to the page).
It requires `OPENAI_API_KEY` in the environment for query embeddings, and a
triple/vector store already populated by the ingestion + extraction +
embedding Dagster jobs.

## Exposing it in the Nexus app system

This uses the **bundled-app** convention from naas-abi #1024 (requires
naas-abi-core ≥ 2.3.0). Nexus discovers an app per
`<module_root>/apps/<name>/manifest.json`; the API auto-serves any `*.html`
under that dir at `/app-html/<module>/<app>/<file>`, and the web host proxies
`/app-html/*` to the API so the iframe loads **same-origin**.

We ship [`src/phases/apps/reverse_search/`](../apps/reverse_search/) with:
- `manifest.json` — `url: "html:index.html"`, which the catalog resolves to
  `/app-html/phases/reverse_search/index.html`. (No environment-specific URL —
  the `html:` shorthand + same-origin proxy make it portable.)
- `index.html` — the UI (the single source of truth; also mounted at
  `/phases/app` by `SearchAPI` for direct / native-dev access).

### Why bundled, not cross-origin

The `naas_abi` module runs `create_app(app)` on the **shared** core API app,
which installs `SecurityHeadersMiddleware`. That sets `X-Frame-Options: DENY`
on **every path except `/app-html/*`** — so embedding the app from its own API
host (e.g. a `tenant.apps` URL pointing at `/phases/app/`) is now frame-blocked.
`/app-html/*` is the only iframe-embeddable path (it gets a permissive CSP
`frame-ancestors` instead).

### Required deployment wiring

Because the embedded page is same-origin with the **web** host, its relative
`/phases/api/*` fetches must be proxied there too. Two `handle` blocks are added
to the web host in [`.deploy/docker/Caddyfile`](../../../../.deploy/docker/Caddyfile):

```caddy
handle /app-html/*    { reverse_proxy abi:9879 }   # bundled app HTML (naas-abi #1024)
handle /phases/api/*  { reverse_proxy abi:9879 }   # this app's backend, same-origin
handle                { reverse_proxy nexus-web:3000 }
```

- **Rebuild `nexus-web`** after the #1024 upgrade so it has the `/app-html`
  route handler + `resolveAppEmbedUrl`.
- **Native `abi dev up`** has no Caddy, so the bundled page's `/phases/api/*`
  calls aren't proxied there — use the direct `/phases/app/` mount on the API
  port (`abi dev ports`) for native-dev testing instead.

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
