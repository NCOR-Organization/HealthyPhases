## Purpose
Provide a searchable PubMed workspace that publishes durable paper metadata and retrievable artifacts for downstream consumers.

## ADDED Requirements
### Requirement: Local module and search workspace
The repository SHALL contain its own copy of the marketplace module, with provenance, and expose its search workspace in Nexus. Queries SHALL have bounded results and validated parameters.
#### Scenario: Search without download
- **WHEN** a user executes a query
- **THEN** the app shows metadata and saves the query and membership without downloading files
#### Scenario: Invalid search
- **WHEN** the query is blank or its bounds are invalid
- **THEN** the request is rejected before external work
### Requirement: Durable explicit ingestion
The app SHALL record an explicit download request and return its identifier. Background jobs SHALL process requests with stable run keys, per-paper progress, and visible terminal outcomes. Retry SHALL be explicit and reuse completed artifacts.
#### Scenario: Orchestrator unavailable
- **WHEN** a user submits while the orchestrator is stopped
- **THEN** the request remains pending for later execution
#### Scenario: Partial download failure
- **WHEN** one paper fails and another downloads
- **THEN** the successful artifact remains published and the failed outcome is visible and retryable
### Requirement: Published artifact contract
The publisher SHALL record query membership independently of paper identity. Ready artifacts SHALL reference successfully stored immutable files with checksums and a versioned publication contract. Unavailable full text SHALL remain a metadata record, not a ready artifact.
#### Scenario: Overlapping queries
- **WHEN** two queries include the same paper
- **THEN** they share its artifact and retain both memberships
#### Scenario: Storage failure
- **WHEN** storing bytes fails
- **THEN** no ready artifact is published for those bytes
