## Purpose
Let Phase v2 users discover published PubMed papers and manually run the pipeline against an exact selection of available artifacts.

## ADDED Requirements
### Requirement: Discover and preview PubMed sources
Phase v2 SHALL offer published PubMed queries and show their ready paper artifacts and storage locations. An absent publisher SHALL be reported as unavailable without disabling existing storage sources.
#### Scenario: Published query
- **WHEN** the user selects a query
- **THEN** the preview lists only ready artifacts belonging to that query
### Requirement: Immutable manual source selection
A manual request SHALL preserve its exact artifact selection at submission. Processing SHALL verify content hashes and scope all pipeline stages to its papers. No Phase v2 run SHALL be triggered by publication alone.
#### Scenario: More papers published after submission
- **WHEN** another artifact is added to the query after a manual request
- **THEN** it is absent from that request and available to a later request
#### Scenario: Artifact changed or missing
- **WHEN** a selected file is missing or fails its checksum
- **THEN** the request reports failure and does not process unrelated papers
#### Scenario: Empty query
- **WHEN** a user submits a query without ready artifacts
- **THEN** the app rejects the request
