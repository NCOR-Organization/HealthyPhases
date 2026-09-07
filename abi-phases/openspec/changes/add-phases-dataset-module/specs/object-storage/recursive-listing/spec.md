## Purpose

Gives callers a way to enumerate every object beneath a storage location, at any depth, so that ingestion pipelines can point at a folder and discover its whole subtree without knowing the folder layout in advance.

## ADDED Requirements

### Requirement: Recursive object listing

The object storage service SHALL expose a listing operation that returns every object at or beneath a given prefix, at any nesting depth. Returned entries SHALL be object keys only; directory or common-prefix placeholders SHALL NOT appear in the result.

Every secondary adapter of the object storage service SHALL support this operation with identical observable behavior, whether by implementing it directly or by inheriting or delegating to an adapter that does.

#### Scenario: Objects nested several levels deep

- **WHEN** a caller lists prefix `papers/` recursively, and the store holds `papers/a.pdf`, `papers/2024/b.pdf`, and `papers/2024/q1/c.pdf`
- **THEN** the result contains all three keys

#### Scenario: Directories are not returned as entries

- **WHEN** a caller lists a prefix recursively and that prefix contains subdirectories
- **THEN** the result contains only object keys, and no entry corresponds to a directory or common prefix

#### Scenario: Missing prefix

- **WHEN** a caller lists a prefix that does not exist
- **THEN** the operation raises the same not-found error the non-recursive listing raises for a missing prefix

#### Scenario: Recursive and non-recursive agree on whether a prefix exists

- **WHEN** a caller lists the same prefix both recursively and non-recursively
- **THEN** either both return results or both raise not-found — the two operations never disagree about whether the prefix is there

Note: stores differ on whether a prefix with no objects under it exists at all. A filesystem keeps the directory; an object store does not represent an empty prefix. This capability therefore guarantees only that the two listing operations agree with each other, not which of the two outcomes a given store produces.

#### Scenario: Result exceeds one provider page

- **WHEN** a recursive listing spans more results than the underlying provider returns in a single response
- **THEN** the operation transparently continues until exhausted and returns the complete set

### Requirement: Non-recursive listing is unchanged

The existing depth-1 listing operation SHALL keep its current behavior and signature. Adding recursive listing SHALL NOT change what existing callers observe.

#### Scenario: Existing caller sees direct children only

- **WHEN** an existing caller invokes the non-recursive listing on a prefix that has nested subdirectories
- **THEN** it receives only the direct children of that prefix, exactly as it did before this change

### Requirement: Adapter conformance is enforced by shared tests

The object storage service SHALL provide a shared, adapter-agnostic test suite covering recursive listing. Every adapter that implements the operation itself SHALL be validated against it. An adapter that only inherits or delegates the operation is covered by the suite run for the adapter it inherits from or delegates to, and SHALL NOT require a test that reaches a live service to prove it.

#### Scenario: A new adapter is added

- **WHEN** a new object storage secondary adapter is introduced that implements listing itself
- **THEN** it can be validated by running the shared conformance suite against it, with no adapter-specific test written for recursive listing

#### Scenario: An adapter only forwards the operation

- **WHEN** an adapter inherits or delegates listing to another adapter rather than implementing it
- **THEN** it needs no conformance run of its own, and no test for it contacts a live service
