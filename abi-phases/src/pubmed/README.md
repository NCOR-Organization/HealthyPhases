# PubMed Library

A repo-local copy of the ABI marketplace PubMed module, with a Nexus app and a
DatasetService-backed publication workflow. See [UPSTREAM.md](UPSTREAM.md) for
provenance and [LICENSE](LICENSE) for the retained upstream license.

## Use in Nexus

1. Enable `pubmed` in the ABI module configuration; it replaces
   `naas_abi_marketplace.applications.pubmed` in this repository.
2. Open **PubMed Library** in Nexus. Search with a PubMed expression, optional
   publication dates, sort order and a result limit (default 100, maximum 1000).
   Either publication date can be used alone; an empty bound leaves that end
   of the date range unrestricted.
3. Review the results and click **Ingest previewed papers**, or choose
   **Ingest all matching papers** for a full-query backfill. The search itself
   saves metadata only. Ingestion creates durable pending work.
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

## Browse the paper library

Open **Papers** to browse the entire saved library with server-side pagination.
The default is **Downloaded papers**: distinct PMIDs with published PDFs, even
when several saved queries or PDF versions refer to the same paper. Choose
**All discovered records** or **Not downloaded** to include metadata-only records.
Not downloaded includes records that are waiting for ingestion, failed, or have
no accessible PDF; it is not a promise that a PDF is available.

Filter by title, author, journal, PMID, PMCID or DOI using a case-insensitive
literal text search, choose a saved query, and optionally set ingestion-date
bounds. Click **Apply filters** to start again at page one. Sort by newest/oldest
ingestion or title, choose 25/50/100 papers per page, and use **Previous**, **Next**
or **Go to page** to reach the full result set. There is no total-paper browse cap.
**View papers** in Full ingestions and **Browse downloaded papers** on a saved
search open this page with the exact query selected.

The ingestion date here is the latest PDF publication timestamp for a paper.
Reusing an existing PDF does not change its timestamp. Date bounds include the
whole UTC day; displayed timestamps use the browser's local timezone. Expand
**PDF versions** to inspect the object storage locations and checksums. Browsing
never schedules downloads or Phase v2 processing. The library is live: use
**Refresh papers** to see newly published records; records may move between pages
as ingestion continues.

`GET /pubmed/api/papers` accepts `search`, `query_id`, `status`
(`published`, `unpublished`, `all`), `ingested_from`, `ingested_until`, `sort`
(`newest`, `oldest`, `title`), `page` (1-based), and `page_size` (1-100).
Its Protobuf-validated response includes the page, matching-paper count, page
count, citation metadata and published artifact references. Count and page rows
are selected together in one dataset query. No dataset schema migration is needed.

## Scheduled queries

Open **Scheduled queries** in PubMed Library to view recurring searches and enable
or disable them. **Delete** removes a schedule after confirmation and prevents
queued occurrences that have not started from executing. Saved searches, downloaded papers and already-started
work are retained. Create a schedule from any saved search, give it a name and choose
an hourly, daily or weekly interval (1, 24 or 168 elapsed hours). The first run is
one interval after creation. The query, publication-date bounds, sort and result
limit are copied from that saved search.

**Download newly found papers** is on by default. Turn it off for search-only
schedules. Each occurrence saves a fresh search; downloads go through the existing
publication request queue. Papers without a PMCID, already published papers, and
papers in pending/running download requests are excluded from new requests. Failed
or unavailable downloads may be retried when a later scheduled search finds them.

Enable/disable changes are durable. Disabling prevents future runs, including
queued occurrences that have not claimed the schedule yet. A started run and its
publication requests may finish. Re-enabling starts a new interval. Stopping
Dagster pauses execution; restarting coalesces missed intervals into one search,
then resumes the interval from that run's start. Dates are stored in UTC and shown
in the browser's local timezone; these are elapsed intervals, not calendar/cron
schedules. The UI shows last-run status, errors and result-limit warnings.

The `pubmed_schedule_sensor` polls every 30 seconds and dispatches at most one due
occurrence per tick. Stable run keys and catalog compare-and-swap protect each
occurrence from duplicate execution. Deletion removes the current schedule row using a catalog-checked replacement;
historical dataset snapshots remain available until their normal expiry.
Completion preserves concurrent toggle edits and never recreates deleted schedules;
failure/cancellation reconciliation allows the next interval to proceed. No
existing search becomes scheduled automatically. Phase v2 automation remains
separate and deferred.

Searches still respect their saved result limit (at most 1000). They do not promise
an exhaustive PubMed backfill or discovery beyond that bounded selection; use
focused queries and review the warning when the limit is reached.

## Published dataset contract, version 1

The `.proto` source is [contracts/pubmed_publication.proto](contracts/pubmed_publication.proto).
Table shapes are derived from its record descriptors. All writes use keyed upsert.
Datasets live in namespace `pubmed`:

| Table | Key | Meaning |
|---|---|---|
| `schedules` | `schedule_id` | Opt-in recurring search settings, enabled state, next occurrence and last-run outcome |
| `backfills` | `backfill_id` | Full-query discovery checkpoints, current publication batch and progress |
| `queries` | `query_id` | Saved search inputs, initial result count and creation time; membership is fixed for previews and grows for backfills |
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

Each interactive search is a fresh query ID with fixed membership. The displayed limit
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

Scheduling Phase v2 pipelines and marketplace publication remain later phases.
Recurring PubMed queries and full-query backfills are supported independently.

## Full-query ingestion

Search as usual, then choose **Ingest all matching papers**. The confirmation
shows the saved query and publication date filters. The preview limit is ignored;
leave both dates empty to cover the query's full publication history. The
**Full ingestions** page shows discovery and download counts and refreshes every
10 seconds. This is an asynchronous, one-time operation; existing recurring
schedules keep their configured search limits.

The `pubmed_backfill_sensor` advances one ready backfill per tick (minimum 30
seconds) through `pubmed_backfill`. Discovery splits non-overlapping numeric PMID
ranges until each contains at most 200 records, avoiding PubMed's 10,000-result
ESearch limit. NCBI describes this strategy in its
[PubMed E-utilities update](https://ncbiinsights.ncbi.nlm.nih.gov/2022/11/22/updated-pubmed-eutilities-live/).
Each run examines at most 20 partitions before saving its checkpoint and yielding.
The initial full-query count is compared against the supported UID range
(1 through 2,147,483,647); a mismatch fails visibly rather than omitting records.

State lives in the additive `pubmed.backfills` dataset. The worker saves the exact
PMIDs before retrieving summaries and submitting a download batch. Deterministic
batch request IDs and conditional insertion prevent a resumed discovery job from
resetting or duplicating a publication request. Existing `pubmed_publish` jobs
handle the PDFs, including checksums, existing artifact reuse, and per-paper
outcomes. Discovery waits for its current publication batch before continuing.

An interrupted discovery job can be **resumed** from the saved ranges and IDs.
Failures or cancellations before a job claims its checkpoint are also recoverable;
stale runs cannot overwrite a later generation. Canceling a discovery job does not
cancel a publication batch that has already been submitted. A download failure
counts as failed work in the completed backfill; retry individual requests using
the existing Ingestion requests view. A new full ingestion also reuses published
PDFs while retrying acquisition for records without a usable artifact.

Counts distinguish discovered records, processed records, published/reused PDFs,
unavailable full text, and failed downloads. The initial count is an estimate:
PubMed is a live index, not a point-in-time snapshot. The operation covers every
partition as observed during traversal; later additions may require another run.
Missing summaries, truncated partitions, and invalid identifiers stop discovery
with an error. No operation promises PDFs for records without accessible full text.

Each backfill has one aggregate query whose membership grows as batches are
queued. Saved bounded searches retain their original membership. The backfill
query can be used as a published-data source; any Phase v2 request still captures
its own fixed artifact manifest. The paper preview is capped at 1,000 records,
and normal manual download requests remain capped at 1,000. Phase v2's existing
1,000-artifact manual manifest limit and separate execution remain unchanged.

API: `POST /pubmed/api/backfills` with a saved `query_id`,
`GET /pubmed/api/backfills`, and
`POST /pubmed/api/backfills/{backfill_id}/resume`. Mutations use the same Nexus
credentials as searches and other ingestion requests. Creating a backfill does
not contact NCBI or download files in the HTTP request.
