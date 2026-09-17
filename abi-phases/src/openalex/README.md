# OpenAlex enrichment

Adds citation and research metadata to records saved by PubMed. Created with `abi new module openalex src`; enabled in the project configurations. No language model is required by this module.

## Use it

1. Search or ingest papers in **PubMed Library**. Enrichment operates on saved records; use full ingestion first if you want records beyond a search preview.
2. Choose a saved query and click **Enrich with OpenAlex**, or open the **OpenAlex enrichment** Nexus app.
3. Queue enrichment. Every record in the saved query at submission is included, even without a PDF. There is no total-paper cap; the worker processes batches of 25 by default.
4. Follow progress in either app. In PubMed's **Papers** page, use **All discovered records** to include papers without PDFs. Filter by OpenAlex status, minimum citations, topic or institution; click a paper's OpenAlex button for details.

Metadata includes OpenAlex ID, DOI/PMID, citation count, authors and institutional affiliations, topics, references, related works, locations and open-access information. Open-access links are source-reported links, not proof that a downloadable PDF is available. This module does not download those links or run the Phase v2 pipeline.

## Matching and refresh

Exact PMID and normalized DOI lookups must agree. Conflicting or unconfirmed identifiers produce an `ambiguous` outcome; no fuzzy title matching occurs. `no_match` means no exact lookup succeeded. A request with ambiguous records completes as `partial`; it does not attach uncertain metadata.

Results are reused for seven days when the input DOI is unchanged. Select **Refresh recent matches too** to bypass that cache. New query members require another request. Citation counts describe the recorded retrieval time. A failed refresh retains the last successful work link and metadata, while marking its latest check as failed.

## Configuration

```yaml
- module: openalex
  enabled: true
  config:
    api_key_secret_name: OPENALEX_API_KEY
    batch_size: 25
    request_budget: 10000
    cache_days: 7
    request_interval_seconds: 1.0
```

Set `OPENALEX_API_KEY` in the existing SecretService environment for authenticated API access. Missing credentials do not block module startup. The server uses an Authorization header; the browser never receives the key. Anonymous lookups are supported when allowed by OpenAlex's current quota policy. Authentication/quota errors interrupt the request with an actionable message.

The HTTP allowance counts every attempt, including retries and redirects. Reaching it pauses the request as `failed`; **Resume** grants another allowance without resetting completed papers. It is a configurable cost/request bound, not a paper limit or estimate of OpenAlex credits. Per-process requests are spaced by one second, with a 30-second timeout, three attempts, exponential retry delay and a 30-second maximum Retry-After delay. For multiple independent worker deployments sharing a key, coordinate the shared quota externally.

## Dataset contracts

All tables use the existing DatasetService catalog, namespace `openalex`. Shapes and validation are defined in `contracts/openalex_enrichment.proto` with Protovalidate. Public rows carry `contract_version = 1`.

| Dataset | Key | Contents |
| --- | --- | --- |
| `works` | `work_id` | Latest normalized source metadata, source update and retrieval timestamps |
| `paper_enrichments` | `pmid` | Exact-match outcome, input DOI, work link, citation/topic/institution projection and check timestamps |
| `run_requests` | `request_id` | Private queue, source snapshot, request budget and progress |
| `request_results` | `request_id`, `pmid` | Private completed-paper checkpoints |

PubMed reads the optional `paper_enrichments` projection via DatasetService, filtered to contract version 1. OpenAlex reads only `pubmed.queries`, `pubmed.query_papers` and `pubmed.papers`; neither module imports the other's application code. The existing shared catalog is the integration boundary. PubMed records and artifact locations are never overwritten. No new persistence service or cross-domain RPC is introduced.

## Dagster and recovery

The `openalex_enrichment_sensor` polls every 30 seconds and submits one pending generation to `openalex_enrich`. Each run processes one batch, checkpoints each paper, and queues the next generation. All worker writes verify the request's current generation/run ownership using DatasetService catalog snapshot tokens. Failure/cancellation sensors mark interrupted generations resumable; late events from old generations cannot reset progress.

A request pins the PubMed catalog snapshot captured at submission and pages its members by PMID. Keep that snapshot until the request completes; expiring it prevents continuation. Completed per-paper outcomes allow recovery if the worker stops after publishing metadata but before advancing its cursor. The source API itself is live, so a large request does not represent a single OpenAlex point-in-time snapshot.

The daemon and worker must share the same configured catalog. Enabling the sensor alone does not create requests. Phase v2 scheduling, graph/vector updates, automatic enrichment of new PubMed arrivals, and fuzzy/manual identity resolution are outside this version.

## API and development

- `GET /openalex/api/status`, `/queries`, `/requests`, `/papers/{pmid}`
- `POST /openalex/api/requests` with `{ "query_id": "<uuid>", "force_refresh": false }`
- `POST /openalex/api/requests/{request_id}/resume`

Mutations use the existing ABI/Nexus bearer authentication. Reads follow the existing research-library API policy; this change introduces no new inter-domain authentication scheme.

Run `make test-openalex`, `make lint`, and `make build`. `make proto` regenerates checked-in descriptors using the repository's existing imported validation descriptor. Tests use synthetic HTTP responses and temporary DuckLake catalogs; they do not consume live API quota. Logs report job status and retain Dagster tracebacks; no new metrics/tracing stack is introduced.
