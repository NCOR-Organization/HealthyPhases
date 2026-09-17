# OpenAlex module

Scaffolded with `abi new module openalex src`. Implements on-demand research metadata enrichment.

- Domain: exact identifier matching, metadata normalization, errors and ownership rules. No framework imports.
- Application: use cases and outbound ports for enrichment storage, paper catalog and HTTP source.
- Secondary adapters: DatasetService and OpenAlex HTTP. Read PubMed's published dataset; never import PubMed application code or modify its records.
- Primary adapter: authenticated mutation endpoints queue jobs, never make external OpenAlex calls.
- Orchestration: `openalex_orchestration.py`, discovered via `OpenalexOrchestration.New()`. Keep business logic in the application service.
- Contracts: `.proto` plus checked-in descriptor `.pb`; `make proto` regenerates descriptors, Protovalidate validates incoming commands and persisted records.
- Nexus app: `apps/openalex`, API base from Nexus runtime config, credentials from existing Nexus auth. Never embed an OpenAlex key in browser code.
- Tests: `tests/openalex_*_test.py`, fake external HTTP plus real temporary DuckLake catalogs; app tests use Node.
- Use `openalex_` filename prefixes and UV. Run `make test-openalex` and scoped Ruff checks.

Dataset contracts and operating defaults are documented in README.md. Respect generation/run ownership on every worker write. Request results allow recovery after publication but before the progress checkpoint. Do not add automatic enrichment or Phase v2 runs without a separate feature request.
