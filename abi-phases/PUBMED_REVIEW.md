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

Phase v2 scheduling and automatic ingestion on publication are deferred. No
marketplace publication, deployment, live model-backed extraction or production
Dagster daemon run was performed. The browser review used a local demo server,
not a deployed Nexus instance.

Datasets have the same deployment-wide visibility and API access boundary as the
existing Phase v2 app. No new persistence service or cross-domain RPC is introduced:
Phase v2 consumes a documented published dataset through DatasetService. NCBI request
spacing is per client, not a distributed account-wide rate limiter. See the module
README for timeout/retry limits and configuring deployment concurrency.

Normal standalone Phase v2 stage jobs retain their existing corpus-wide defaults;
full pipeline runs now follow the selected papers. Legacy PDFs stay in place and
are not automatically backfilled into the new datasets.
