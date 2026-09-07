## Purpose

Runs prompts against chunks with an AI model and records the results durably, doing each unit of work exactly once so that re-running a pipeline costs nothing for what has already been extracted.

## ADDED Requirements

### Requirement: Extraction work is identified by chunk, model and prompt

Every unit of extraction work SHALL be identified by the combination of one chunk, one model and one prompt version. That combination SHALL yield a stable `extraction_id`.

#### Scenario: The identity of a unit of work

- **WHEN** the same chunk, model and prompt version are named twice
- **THEN** both resolve to the same `extraction_id`

#### Scenario: Any input differs

- **WHEN** two units of work differ in their chunk, their model, or their prompt version
- **THEN** they resolve to different `extraction_id` values

### Requirement: Already-completed work is not repeated

Before running, the module SHALL determine which of the candidate combinations already have a completed extraction and SHALL execute only the remainder.

#### Scenario: Nothing new to do

- **WHEN** a run is requested whose every candidate combination already has a completed extraction
- **THEN** no model calls are made and the run reports that there was nothing to do

#### Scenario: A prompt is edited

- **WHEN** a prompt template is edited and a run is requested over the same chunks and model
- **THEN** every combination is treated as new work, and the extractions produced under the previous prompt version remain intact

#### Scenario: New papers arrive

- **WHEN** new papers are ingested and chunked, and a run is requested over the same model and prompt
- **THEN** only the chunks that have no completed extraction for that model and prompt are executed

#### Scenario: A previous attempt failed

- **WHEN** a combination was attempted before and recorded as failed
- **THEN** it is treated as outstanding work and retried on the next run

### Requirement: Extractions dataset

Completed and failed extraction attempts SHALL be recorded in an `extractions` dataset keyed on `extraction_id`. Each row SHALL carry the `extraction_id`, the `chunk_id`, the model identifier, the `prompt_id`, the run it belonged to, the outcome, the model's response, the number of items produced, and the time it completed.

The model's response SHALL be stored verbatim as a structured value that can be queried without re-parsing it in the caller, so that a change to how output is interpreted never requires paying for the model call again.

#### Scenario: An extraction succeeds

- **WHEN** a unit of work completes successfully
- **THEN** a row records a successful outcome, the verbatim response and the item count

#### Scenario: An extraction fails

- **WHEN** a unit of work fails, whether by model error or unparseable output
- **THEN** a row records a failed outcome and the reason, and the run continues with the remaining work

#### Scenario: One failure does not abort the run

- **WHEN** some units of work in a run fail and others succeed
- **THEN** the successful ones are recorded and the run reports how many succeeded and how many failed

#### Scenario: The raw response is queried

- **WHEN** a caller queries the `extractions` dataset for extractions whose response contains more than a given number of items
- **THEN** the query resolves against the stored response directly, without the caller parsing it first

#### Scenario: The same unit of work is recorded twice

- **WHEN** the same `extraction_id` is written more than once, whether by a retry or by two runs overlapping
- **THEN** the dataset holds exactly one row for it, carrying the most recent outcome

### Requirement: Extracted items dataset

The individual items produced by an extraction SHALL be recorded in an `extracted_items` dataset keyed on an item identifier, one row per item, each carrying its `extraction_id`, its `chunk_id`, its `paper_id`, its position within the extraction, and its text.

#### Scenario: An extraction produces several items

- **WHEN** an extraction returns several items
- **THEN** one row per item is recorded, each traceable back to its extraction, chunk and paper

#### Scenario: An extraction produces no items

- **WHEN** an extraction completes successfully but returns no items
- **THEN** the extraction is recorded as successful with an item count of zero, and no item rows are recorded

#### Scenario: An extraction is re-recorded

- **WHEN** an extraction that already has item rows is recorded again
- **THEN** its items are not duplicated

### Requirement: Runs are recorded

Each invocation of extraction SHALL be recorded in an `extraction_runs` dataset carrying a run identifier, the inputs the run was scoped to, when it started, when it finished, and its outcome counts.

#### Scenario: A run completes

- **WHEN** an extraction run finishes
- **THEN** its row records the chunker, model and prompt it was scoped to, its start and end times, and how many units succeeded, failed, and were skipped as already done

### Requirement: Runs are scopable

A caller SHALL be able to scope a run to a chosen model, prompt and chunking mechanism, and optionally to a subset of papers or a maximum number of chunks.

#### Scenario: A limited trial run

- **WHEN** a caller requests a run scoped to one prompt, one model and a small maximum number of chunks
- **THEN** at most that many outstanding units of work are executed
