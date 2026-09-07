## Purpose

Publishes chunks and extracted items as embeddings in vector collections so that the search app can retrieve them semantically and resolve every hit back to its source paper.

## ADDED Requirements

### Requirement: Dedicated vector collections for chunks and extracted items

The module SHALL maintain two vector collections of its own: one holding chunk text, one holding extracted item text. It SHALL NOT write into the collections used by the existing phases module.

#### Scenario: Collections are created on first run

- **WHEN** vector projection runs and the module's collections do not yet exist
- **THEN** they are created and populated

#### Scenario: The existing module's collections are untouched

- **WHEN** vector projection runs while the existing phases module's collections are present
- **THEN** those collections are unchanged

### Requirement: Vectors carry resolvable provenance

Each stored vector SHALL carry the identifiers needed to resolve it back to its source. A chunk vector SHALL resolve to its chunk and paper. An extracted item vector SHALL resolve to its item, its extraction, its chunk, its paper, and the model and prompt version that produced it.

#### Scenario: A semantic search hit is resolved

- **WHEN** the search app retrieves an extracted item vector
- **THEN** it can present the source paper, the source chunk, and which model and prompt version produced the item

### Requirement: Projection is idempotent and incremental

Vector projection SHALL be safe to run repeatedly. Re-running SHALL only embed rows that have not yet been embedded, and SHALL NOT create duplicate vectors.

#### Scenario: Projection runs twice with no new data

- **WHEN** vector projection runs again and no new chunks or extracted items exist
- **THEN** no embeddings are computed and the collections are unchanged

#### Scenario: New extracted items arrive

- **WHEN** new extracted items are recorded and projection runs again
- **THEN** only the new items are embedded and added

#### Scenario: Projection is interrupted

- **WHEN** a vector projection run is interrupted partway and is started again
- **THEN** it embeds the outstanding rows without re-embedding or duplicating what it already stored

### Requirement: A projection run reads one coherent instant

A vector projection run SHALL read every dataset it draws from at a single, consistent point in time, so that concurrent writes cannot make a run embed a partially written set of rows.

#### Scenario: A write lands mid-run

- **WHEN** new extracted items are recorded while a vector projection run is in progress
- **THEN** that run embeds only the items it started from, and the new ones are embedded by the next run
