## Purpose

Turns a set of object-storage locations into a durable, queryable catalog of papers, so that every downstream stage of the pipeline refers to a stable paper identity rather than to a file path that may move.

## ADDED Requirements

### Requirement: Papers are discovered recursively from selected locations

A caller SHALL be able to name one or more object-storage locations as the source of papers. The module SHALL discover every object at or beneath each named location, at any depth.

#### Scenario: A location with nested folders

- **WHEN** ingestion runs against a location whose subtree holds papers in nested folders
- **THEN** every paper in the subtree is discovered, regardless of nesting depth

#### Scenario: Multiple locations

- **WHEN** ingestion runs against several locations at once
- **THEN** papers from every named location are discovered in a single run

#### Scenario: Location does not exist

- **WHEN** ingestion runs against a location that does not exist
- **THEN** the run reports that location as failed, with the reason, and still processes the remaining locations

### Requirement: Papers dataset

Discovered papers SHALL be recorded in a `papers` dataset in the module's namespace. Each row SHALL carry a `paper_id`, the storage location it was read from, the file name, the size, the content hash, a media type, and the time it was first discovered.

`paper_id` SHALL be derived from the paper's content, so the same content discovered at two paths yields one identity.

#### Scenario: A paper is discovered for the first time

- **WHEN** ingestion discovers a paper whose content hash is not yet in the `papers` dataset
- **THEN** a row is recorded with its `paper_id`, source location, file name, size, content hash, media type and discovery time

#### Scenario: The same paper is discovered again

- **WHEN** ingestion runs a second time over an unchanged location
- **THEN** the dataset still holds exactly one row for that `paper_id`

#### Scenario: The same content appears at two paths

- **WHEN** the same file content is discovered at two different storage locations
- **THEN** both are recognised as one `paper_id` and the paper is not extracted twice downstream

### Requirement: Paper text is extracted and stored

For each paper, the module SHALL produce a plain-text or markdown rendering suitable for chunking, store it in object storage, and record its location on the paper's row.

#### Scenario: A PDF is ingested

- **WHEN** a PDF paper is ingested
- **THEN** a text rendering of it is written to object storage and the paper's row records where to find it

#### Scenario: Text rendering already exists

- **WHEN** ingestion re-runs for a paper whose text rendering already exists
- **THEN** the rendering is not recomputed

#### Scenario: A paper cannot be rendered

- **WHEN** a discovered object cannot be rendered to text
- **THEN** the run records the failure against that paper and continues with the remaining papers

### Requirement: Ingestion is resumable

An interrupted ingestion run SHALL be safe to re-run. Re-running SHALL only do the work that has not already been recorded.

#### Scenario: Run is interrupted midway

- **WHEN** an ingestion run is interrupted after processing some papers and is then started again over the same locations
- **THEN** the already-recorded papers are skipped and only the remaining ones are processed
