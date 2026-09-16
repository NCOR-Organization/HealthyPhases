# PubMed dataset app review

## Delivered behavior

- Repo-local `src/pubmed`, copied from ABI marketplace revision
  `731eb3ce069c05864a6cda0e1503aa43c66d7328`, with license and provenance retained.
- Nexus PubMed Library: search with publication date bounds, saved queries,
  result previews, explicit download requests, progress, errors and retry.
- A Scheduled queries page to create, enable, disable and delete recurring searches.
  Each schedule can publish newly available PDFs. Atomic occurrence claims prevent
  duplicate execution; late completion cannot recreate a deleted schedule.
- Public version 1 datasets in the `pubmed` namespace and immutable PDF objects
  at `pubmed/papers/<PMCID>/<SHA256>.pdf`.
- Phase v2 can select a published query for a manual run. An immutable manifest
  fixes the artifact selection; checksums are verified when reading objects.
  Selected paper IDs carry through ingestion, chunking, extraction, relation,
  graph and vector projection. A missing manifest fails without a storage scan.
- The current Phase v2 workspace and saved storage pipeline configurations remain
  available. Both apps send Nexus authentication on mutations.

## Validation

The publisher and source tests cover real DuckLake persistence, concurrent claims,
publication idempotency, deletion conflicts, source manifests and checksum failures.
Browser logic tests cover search dates, stale responses, schedule navigation,
enable/disable/delete, source selection and authenticated requests.

The original local Nexus review also exercised search, schedule creation,
enabling/disabling, and confirmed/canceled deletion in Chromium without JavaScript
errors. The live NCBI smoke test fetched search results and a sample PDF into memory.
Live provider/model tests remain opt-in.

Reproduce the release checks with `make test lint build`; use `make test-search`
for search-specific checks and `make test-pubmed-network` for the live NCBI smoke test.
CI runs publisher/source, pipeline and reverse-search checks on pull requests.

## Review entry points

- `src/pubmed/README.md`: app use, datasets and operational defaults.
- `src/pubmed/application/pubmed_service.py`: publication and request lifecycle.
- `src/pubmed/application/pubmed_schedules.py`: schedule claims and transitions.
- `src/pubmed/adapters/secondary/pubmed_dataset_store.py`: schemas and atomic writes.
- `src/pubmed/apps/search/index.html`: Nexus app.
- `src/phases_v2/sources/`: public dataset consumption and fixed manifests.
- `openspec/changes/add-pubmed-dataset-app/`: initial proposal, specs and tasks.

## Boundaries and operational assumptions

Automatic Phase v2 ingestion and pipeline schedules remain a later phase. The
agreed behavior is automatic registration/text rendering of newly published papers,
with full extraction and projection enabled per source using saved settings.
This release provides recurring PubMed searches/publication and manual Phase v2 runs.

Datasets have deployment-wide visibility, following the existing DatasetService
boundary. Phase v2 reads the public data contract without importing publisher
implementation code. No new persistence service or cross-domain RPC is introduced.

NCBI request spacing is per client. See the module README for HTTP timeouts,
retry/download limits, bounded search windows and concurrency configuration.
Standalone Phase v2 stage jobs retain corpus-wide defaults. Existing PDFs remain
in place; this change does not backfill them into PubMed datasets or republish the
module to the marketplace.
