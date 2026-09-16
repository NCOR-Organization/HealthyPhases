# PubMed dataset app review

## Review range

Branch: `feat/pubmed-dataset-app`.
Base feature review on commit `9d37ce1`, which separately preserves the existing
uncommitted Phase v2 work needed by this change. The original worktree is untouched.

```sh
git diff 9d37ce1..feat/pubmed-dataset-app -- abi-phases
```

## Delivered behavior

- Repo-local `src/pubmed`, copied from ABI marketplace revision
  `731eb3ce069c05864a6cda0e1503aa43c66d7328`; provenance/license retained.
- Local module configuration and legacy Phase agent references updated.
- Nexus PubMed Library: bounded search, saved queries, result previews, explicit
  ingestion requests, per-paper progress, failure details and retry.
- Current NCBI E-utilities search and PMC Cloud PDF retrieval, with bounded HTTP
  retries, download-size checks, host restrictions and content verification.
- Public version 1 datasets and immutable content-addressed paper objects.
- PubMed Dagster request, failure and cancellation sensors, with atomic claims.
- Phase v2 PubMed source selection, immutable manifests and manually submitted
  runs. Paper scope is carried through ingestion, chunking, extraction and both
  projections; a missing manifest never falls back to scanning a broad prefix.
- Protobuf/Protovalidate contracts and reproducible code generation. Both apps,
  descriptor sets and Phase v2 prompt assets are included in built packages.

## Validation

- `make test`: 438 Python tests passed, 3 opt-in cases skipped; all 12 frontend
  tests passed. The live NCBI smoke check also passed separately.
- Focused follow-up tests cover missing-manifest failure and cancellation recovery.
- `make test-pubmed-network`: passed against public NCBI; one live PubMed query and
  one sample PMC PDF downloaded into memory, without creating publication records.
- `make proto lint build`: passed. Inspected the wheel for app HTML/manifests,
  validation descriptor sets and prompt templates.
- Headless Chromium: searched synthetic demonstration records, submitted a request,
  verified pending status, checked a 390px mobile viewport and captured a screenshot;
  no browser exceptions or mobile horizontal overflow.
- `openspec validate add-pubmed-dataset-app --strict`: passed.

## Review entry points

- `src/pubmed/README.md`: app use, dataset contract and operational defaults.
- `src/pubmed/application/pubmed_service.py`: publication ordering and request lifecycle.
- `src/pubmed/adapters/secondary/pubmed_dataset_store.py`: schemas, keyed writes and atomic claim.
- `src/pubmed/apps/search/index.html`: Nexus app.
- `src/phases_v2/sources/`: public dataset consumption and fixed manifests.
- `openspec/changes/add-pubmed-dataset-app/`: proposal, specs, design and task checklist.

## Boundaries and operational assumptions

Phase v2 scheduling and automatic ingestion on publication are deferred.
The agreed second-phase behavior is to automatically register newly published
PubMed papers and render their text. Sources can opt into the full pipeline
(chunking, LLM extraction, and graph/vector updates) using saved model and prompt
settings. Full pipeline execution is enabled per source. No
marketplace publication, production deployment, live model-backed extraction or
production Dagster daemon run was performed. The initial browser review used a
local demo server; the subsequent local Nexus verification is recorded below.

Datasets have the same deployment-wide visibility and API access boundary as the
existing Phase v2 app. No new persistence service or cross-domain RPC is introduced:
Phase v2 consumes a documented published dataset through DatasetService. NCBI request
spacing is per client, not a distributed account-wide rate limiter. See the module
README for timeout/retry limits and configuring deployment concurrency.

Normal standalone Phase v2 stage jobs retain their existing corpus-wide defaults;
full pipeline runs now follow the selected papers. Legacy PDFs stay in place and
are not automatically backfilled into the new datasets.


## Local stack review (2026-09-16)

Started with `abi dev up -d` from this worktree, using the untracked
`config.review.yaml` selected by `ENV=review` in `.env`. The user authorized copying
the original `.env`; the copy has mode 0600 and remains Git-ignored. Review ports,
local admin credentials, SQLite catalogs and filesystem storage are separate.

- Nexus: http://localhost:12789
- ABI API: http://localhost:10668
- Dagster: http://localhost:11789
- Oxigraph: http://localhost:8667/health
- Login: `admin@example.com` / `admin` (development instance only).
- Workspace: PubMed Review; PubMed Library and Phases Pipeline are enabled.

Verified API login, the app catalog, PubMed queries, Phase v2 PubMed source
listing, loaded Dagster sensors, and browser login/opening PubMed Library inside
Nexus with no JavaScript exceptions. No paper or LLM pipeline run was submitted.

A local change in `.abi/libs/naas-abi/naas_abi/apps/nexus/apps/web/next.config.js`
keeps React's precompiled bundles and property-information out of Next 14's SWC
transform; otherwise their rewritten exports prevent the frontend from compiling.
This dependency-worktree change is uncommitted and available for review.
The legacy Phase reverse-search endpoint still reports missing process-environment
OpenAI credentials; the PubMed and Phase v2 app endpoints mounted successfully.

Stop this instance from the worktree with `.venv/bin/abi dev down`.


## Follow-up: scheduled PubMed queries

The PubMed app now has a Scheduled queries page for creating recurring searches
and toggling them on/off. Schedules are stored in the additive `pubmed.schedules`
dataset. A separate Dagster job refreshes the saved search and optionally queues
new downloads; Phase v2 automation remains deferred. See `src/pubmed/README.md`
for interval semantics, failure recovery, bounded-search limits and pause behavior.


Scheduled-query verification: `make test lint build` passed (457 Python tests,
3 opt-in skips; 15 frontend tests). Tests cover schedule validation, due/disabled
behavior, duplicate occurrences, pause during a run, search-only mode, failure
recovery, real DuckLake persistence/concurrent claims, and the Dagster job.
The running local Dagster instance exposes `pubmed_scheduled_query` and
`pubmed_schedule_sensor`. Browser creation, enable and disable checks passed with
no JavaScript errors. A clearly named review example remains disabled.
