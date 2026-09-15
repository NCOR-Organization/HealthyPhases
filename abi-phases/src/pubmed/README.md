# PubMed Library

A repo-local copy of the ABI marketplace PubMed module, with a Nexus app and a
DatasetService-backed publication workflow. See [UPSTREAM.md](UPSTREAM.md) for
provenance and [LICENSE](LICENSE) for the retained upstream license.

## Use in Nexus

1. Enable `pubmed` in the ABI module configuration; it replaces
   `naas_abi_marketplace.applications.pubmed` in this repository.
2. Open **PubMed Library** in Nexus. Search with a PubMed expression, optional
   publication dates, sort order and a result limit (default 100, maximum 1000).
3. Review the results and click **Ingest this query**. The search itself saves
   metadata only. The ingestion action creates a durable pending request.
4. Run the existing ABI Dagster daemon and code location. The
   `pubmed_run_request_sensor` picks up pending requests every 30 seconds and
   launches `pubmed_publish`. Requests wait safely while the daemon is stopped.
5. Refresh ingestion status to see paper outcomes. **Retry remaining** creates a
   new request for failed/unavailable papers and preserves published artifacts.
6. In **Phases Pipeline**, select **PubMed dataset**, choose a published query,
   preview its artifact locations and manually request a pipeline run.

The agent uses the same search, queue and status operations. Its ingestion tool
now returns a request identifier instead of downloading synchronously.
The existing RDF pipeline and PDF-stream integration entry point remain usable.

```yaml
modules:
  - module: pubmed
    enabled: true
    config:
      datastore_path: pubmed
      ncbi_email: ""  # Set an operational contact for NCBI, if available.
      ncbi_api_key: ""  # Use a SecretService template when configuring a key.
```

DatasetService and ObjectStorageService must be configured. Dataset initialization
is additive and idempotent. Existing legacy objects under `pubmed/pdfs` remain;
new artifacts use `pubmed/papers/<PMCID>/<SHA256>.pdf`. No automatic backfill of
legacy files or dataset schema migration is performed.

## Published dataset contract, version 1

The `.proto` source is [contracts/pubmed_publication.proto](contracts/pubmed_publication.proto).
Table shapes are derived from its record descriptors. All writes use keyed upsert.
Datasets live in namespace `pubmed`:

| Table | Key | Meaning |
|---|---|---|
| `queries` | `query_id` | A saved, bounded search, its exact inputs, total result count and retrieval time |
| `papers` | `pmid` | Citation metadata, PMCID, DOI and authors |
| `query_papers` | `query_id`, `pmid` | Query membership independent of artifact identity |
| `artifacts` | `artifact_id` | Ready, immutable stored PDFs with SHA-256, source URL, selected PMC version and license |
| `run_requests` | `request_id` | Pending/running/terminal state and per-PMID outcomes |

`queries.contract_version` and `artifacts.contract_version` are currently `1`.
Consumers join membership to `artifacts` on PMID and select `status = 'ready'`.
An artifact becomes ready only after object storage accepts its bytes. Storage
locations use the ObjectStorageService prefix/key convention, not local OS paths.
Artifacts do not contain credentials. A PMID/PMCID is a literature identifier;
SHA-256 is the actual file identity used for Phase v2 deduplication.

Each saved search is a fresh query ID with fixed membership. The displayed limit
is a limit on matching PubMed records, including records without downloadable
full text. Missing summaries fail the search rather than publishing a misleading
partial selection. Queries are unmodified PubMed expressions; filters are optional.

Phase v2 reads this public dataset through its own secondary adapter, snapshots
exact artifact references before queuing a request and verifies hashes before
rendering. This published-data boundary has no direct Python calls between domains
and adds no RPC service or DDS endpoint. Private publisher request state is owned
by PubMed; Phase v2 uses its own request and source-manifest datasets.

## Acquisition and reliability

NCBI removed legacy article-distribution files from FTP in August 2026. Downloads
use the current public PMC Cloud service, not `oa_file_list.txt`:
https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/
https://pmc-oa-opendata.s3.amazonaws.com/README.txt

The client discovers actual PMC version prefixes and reads their JSON metadata.
It prefers a published PDF over an author manuscript, then the highest numbered
available version within that category, and records that choice. NCBI version
numbers alone do not establish publication recency. No accessible PDF yields an
`unavailable` outcome, and no ready artifact. Publisher MD5 values are verified
when supplied; local publication always records SHA-256. Downloads are limited to
100 MiB, allowlisted to the public bucket, and reject redirects and non-PDF data.

Initial defaults: 30-second HTTP timeout, three attempts for transient HTTP
failures, 1/2-second retry delays, and 340 ms spacing per client. The sensor
submits one oldest pending request and waits while a request is running. A
catalog-snapshot compare-and-swap claim prevents two workers owning one request.
API searches in separate workers/deployments still share NCBI's account/IP quota;
there is no distributed rate limiter in this phase. Reduce API concurrency if
rate-limited. Retries remain bounded. These are interim operational defaults.

Per-paper outcomes checkpoint after each attempt. Failed downloads do not discard
successful publications. `pubmed_failure_sensor` marks requests failed when their
Dagster runs fail. `pubmed_cancellation_sensor` also reconciles canceled runs so their requests can
be retried. A stuck worker can be canceled through Dagster. A worker crash after a blob write can leave an unreferenced
content-addressed object; retry reuses the same key. No blob deletion is automatic.
Logs use the existing ABI/Dagster logging, with no new observability stack.
The app inherits ABI's existing API access controls and deployment-wide dataset
visibility, like the current Phase v2 app. Configure authorization at that boundary.

## Development and review

From `abi-phases/`:

```sh
make install
make proto
make test-pubmed
make test
make build
```

`make test-pubmed-network` opts into one read-only NCBI search and one public sample
PDF download into memory. It does not enqueue jobs or publish datasets.
Agent tests require a live engine/model and are opt-in with
`PUBMED_LIVE_AGENT_TESTS=1`. Normal tests use fakes and temporary real DuckLake
catalogs. Protobuf descriptor sets are checked in; `make proto` regenerates them
with protoc and the repository's existing validation descriptors.

Scheduling Phase v2 pipelines, periodic PubMed queries, marketplace publication,
and deployment are intentionally left for later phases.
