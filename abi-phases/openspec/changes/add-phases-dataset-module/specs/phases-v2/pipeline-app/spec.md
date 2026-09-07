## Purpose

Gives a user a place in the Nexus workspace to choose what the pipeline should run over — which storage locations, which chunker, which prompt, which model — and to request that run and follow it without leaving the UI.

## ADDED Requirements

### Requirement: The app is discoverable in the workspace

The module SHALL publish an app that the workspace's apps listing discovers and can enable, with a name, description, icon and category.

#### Scenario: The app appears in the apps listing

- **WHEN** a user opens the workspace apps listing with the module installed
- **THEN** the pipeline app is listed and can be enabled for the workspace

#### Scenario: The app is opened

- **WHEN** an enabled pipeline app is opened
- **THEN** its interface loads within the workspace

### Requirement: Pipeline inputs are chosen in the app

The app SHALL let a user select the object-storage locations to ingest from, the chunking mechanism, one or more prompt versions, and the AI model. The prompt and model choices SHALL be drawn from what the module has published, not typed by hand.

Every published prompt SHALL be selected by default: extracting a single dimension of a corpus is the exception, not the usual intent.

The app SHALL also show which documents the selected locations contain, at any depth, and which of them have already been ingested — so a user can see what a run would cover before requesting it.

#### Scenario: Choosing a prompt and model

- **WHEN** a user opens the run form
- **THEN** the prompt versions and models offered are those the module currently publishes, and every prompt is already selected

#### Scenario: Seeing what a location holds

- **WHEN** a user selects one or more storage locations
- **THEN** the documents beneath them are listed, at any depth, each marked as new or already ingested

#### Scenario: A selected location cannot be read

- **WHEN** one of the selected locations cannot be listed
- **THEN** the others are still shown and the failure is reported rather than emptying the list

#### Scenario: Browsing storage locations

- **WHEN** a user picks the source of papers
- **THEN** they can browse the locations beneath the module's own papers root and select one or more

#### Scenario: Another module's data is not offered as a paper source

- **WHEN** other modules have written their own data into the same object storage
- **THEN** their prefixes are not offered, because the chooser is scoped to the module's configured papers root rather than to the storage root

#### Scenario: The papers root does not exist yet

- **WHEN** no papers have been placed under the configured root
- **THEN** the root is still offered, and the preview reports it as empty rather than the chooser being blank

#### Scenario: A required input is missing

- **WHEN** a user attempts to submit a run without selecting every required input
- **THEN** the app refuses to record it and states which input is missing

### Requirement: Runs are requested, not launched

Submitting the form SHALL record a run request carrying the selected inputs, in a `run_requests` dataset keyed on a request identifier. The app SHALL NOT execute the pipeline and SHALL NOT contact the orchestrator.

Recording the request SHALL be the app's only responsibility for starting work: a request that has been recorded is a request that will eventually run.

#### Scenario: A run is requested

- **WHEN** a user submits the run form
- **THEN** a pending request row is recorded with the selected locations, chunker, prompts and model, and the app reports its request identifier

#### Scenario: The orchestrator is not running

- **WHEN** a user submits a run while the orchestrator is stopped
- **THEN** the request is still recorded successfully, and it is picked up once the orchestrator is running again

#### Scenario: The app is closed after requesting a run

- **WHEN** a user closes the app after submitting a request
- **THEN** the request is unaffected and runs to completion

#### Scenario: The request store is unreachable

- **WHEN** a user submits a run and the request cannot be recorded
- **THEN** the app reports the failure and does not claim the run was requested

### Requirement: Pending requests are picked up and run exactly once

The orchestrator SHALL detect pending run requests without being called, and SHALL start one run per request. A request SHALL NOT produce a second run, however many times it is observed while pending.

#### Scenario: A pending request is detected

- **WHEN** a pending request exists and the orchestrator evaluates for new work
- **THEN** a run starts carrying that request's inputs, and the request is no longer pending

#### Scenario: The orchestrator has just been started

- **WHEN** the orchestrator starts for the first time, with nobody having enabled anything by hand
- **THEN** it is already watching for run requests — a recorded request that nothing is looking for is indistinguishable from a broken app

#### Scenario: A request is observed repeatedly

- **WHEN** the same pending request is observed more than once before its run is recorded as started
- **THEN** only one run is created for it

#### Scenario: Several requests are pending

- **WHEN** more than one request is pending at the same time
- **THEN** each produces its own run

#### Scenario: A request's run fails

- **WHEN** the run started for a request fails
- **THEN** the request is recorded as failed with the reason, and it is not silently retried

### Requirement: Request outcomes are visible

The app SHALL show the status of the requests it recorded, and on completion SHALL report how many units of work succeeded, failed, and were skipped as already done.

#### Scenario: Following a request

- **WHEN** a user views a request they submitted
- **THEN** they see whether it is pending, running, succeeded or failed

#### Scenario: A completed request's counts

- **WHEN** the run for a request completes
- **THEN** the app reports its succeeded, failed and skipped counts

### Requirement: The existing app is unaffected

Adding this app SHALL NOT change the behavior, availability or enablement of the existing phases reverse-search app.

#### Scenario: Both apps are installed

- **WHEN** both this module and the existing phases module are installed
- **THEN** both apps appear in the workspace listing and each works as before
