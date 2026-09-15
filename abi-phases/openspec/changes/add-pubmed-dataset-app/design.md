## Context
See proposal.md. Existing Phase v2 services use DatasetService and object storage with a durable request sensor. Its ingestion is content-addressed; chunking/extraction already support paper filters, but orchestration omits them. The current collection editor is limited to its own prefix. PMC legacy FTP distribution was removed in August 2026.

## Goals / Non-Goals
Goals: a self-contained local publisher and explicit, reproducible consumer requests.
Non-goals: scheduling Phase v2, introducing persistence backends or RPC services, deploying, or publishing upstream.

## Decisions
- Copy the complete marketplace module into src/pubmed, rebase its internal imports, document source revision and license, and route existing module references locally. Retain legacy search/tool entry points while delegating new acquisition to injected ports.
- Publish tables in pubmed namespace: queries, papers, query_papers, artifacts, run_requests. Contract version 1; immutable content-hash storage keys below configured datastore_path. Use upserts exclusively. Keep per-request paper outcomes in JSON and never claim readiness before storage succeeds.
- Version the DTOs in .proto with Protovalidate. Generate descriptor sets with protoc and derive publisher dataset shapes from those descriptors. Validate at server boundaries.
- Consume the versioned, documented public dataset through a Phase v2 secondary adapter. This is shared published data, not a cross-domain service call; there are no Python dependencies on PubMed implementation and no new endpoints needing DDS. No arbitrary cross-namespace SQL from the browser.
- Snapshot exact artifact references into a new Phase v2 source_manifests table before publishing a pending request. This avoids changing existing request-table schemas. A dataset:pubmed source marker in the request makes a missing manifest a hard failure, preventing fallback to a prefix scan. The job reads only those objects, checks SHA-256, and carries paper_ids through all stages. Ordinary storage selections also carry discovered paper IDs downstream.
- Dagster polls PubMed pending requests every 30 seconds with stable request-id run keys. The job claims the request, checkpoints per-paper results, and marks terminal status. A failure sensor reconciles interrupted jobs. Explicit retry creates a fresh request. The sensor dispatches one oldest pending request at a time and waits while a request is running; claims use compare-and-swap; transient HTTP calls retry at most three times with bounded delays and a 30-second timeout. No periodic PubMed search or Phase v2 source sensor.
- Search is bounded to 100 results by default, 1000 maximum, with pagination and visible total/truncation. PMC Cloud HTTPS metadata/file discovery replaces oa_file_list/FTP. A paper lacking an accessible PDF is unavailable, not ready.

## Risks / Trade-offs
- Dataset keys are advisory: use keyed upsert and catalog snapshot compare-and-swap for claims. Snapshot conflicts are retried boundedly.
- External API and deployment access cannot be proven by mocks: provide an opt-in network smoke test and report its execution separately.
- Module APIs inherit the deployment's existing API authorization boundary; do not add browser credentials or arbitrary download URLs. Publisher data is deployment-wide, as are current Phase v2 datasets.
- Snapshot artifacts consume a little extra dataset space, preserving provenance and preventing later query changes from expanding a run.

## Migration Plan
Load pubmed instead of marketplace PubMed and retain datastore_path. Existing legacy PDFs remain untouched; new runs publish versioned checksum paths. All new datasets are additive. Rollback restores module configuration and previous application version; published objects and datasets can remain for later recovery.
