## Why
PubMed currently exposes agent tools but no reviewable search/download workspace or durable publication catalog. A repo-local copy enables iteration while Phase v2 can consume published papers through the existing dataset and object-storage services.

## What Changes
- Copy the marketplace PubMed module into `src/pubmed`, preserving provenance and moving configuration and legacy agent references to the local module.
- Add a Nexus app to search PubMed, preview results, submit durable download requests, inspect per-paper outcomes, and retry failed downloads.
- Publish versioned query, paper, membership, request, and artifact datasets using DatasetService; store downloaded files under the configured PubMed prefix.
- Replace the obsolete PMC FTP download path with the current public PMC Cloud distribution.
- Add a PubMed request sensor and jobs. Only explicitly submitted requests run.
- Add a PubMed dataset source to the Phase v2 app, resolve exact published artifacts into manually submitted requests, and carry paper scope through ingestion, chunking, extraction and projection.
- Scheduled and automatic Phase v2 pipeline execution are deferred to a later change.

## Capabilities
### New Capabilities
- `pubmed/publication`: Repo-local module, search app, durable ingestion jobs, and published dataset contract.
- `phases-v2/pubmed-source`: Dataset source discovery, query selection, exact artifact preview and manually scoped pipeline runs.
### Modified Capabilities
None; existing Phase v2 planning remains in its active change.

## Impact
`src/pubmed`, `src/phases_v2`, local module references in `src/phases`, module configuration, package assets and Make targets. Existing DatasetService and ObjectStorageService adapters are reused. Consumers read a documented public publication dataset through a secondary adapter; there are no direct cross-domain Python calls or new RPC endpoints. No scheduling, new persistence backend, deployment, or marketplace publication is included.
