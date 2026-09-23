# Qualified effects: rollout and reviewed pilot

This changes the derived relation table and extraction contract. A decrease in
social support that increases stress remains source change `decreases`, target
effect `increases`. Prevention is distinct from an opposite effect. No sign
multiplication is performed. Evidence supports an extracted claim, not an
independently established causal fact.

## Before production deployment

1. Record the running application revision and existing relation schema. Take
   the deployment's normal catalog/data backup or snapshot. Keep raw papers,
   chunks, prompts, extractions and extracted_items; never delete these to migrate.
2. Pause scheduled and manual extraction/projection jobs and wait for in-flight
   writes to finish. Disable Effects search/export during the maintenance window.
   This change does not implement distributed migration locking.
3. Deploy the new application to the maintenance environment. Startup creates
   missing datasets but does not alter an existing relation table. A schema-drift
   warning is expected until the rebuild completes.
4. From the deployed `abi-phases` directory, using its configured environment:

   ```sh
   uv run abi run script src/phases_v2/projection/probabilistic_backfill.py -- --rebuild
   ```

   This **drops and recreates only the derived probabilistic_relations table**,
   then reads saved source extractions and reprojects them. It makes no model
   calls. The operation is not atomic: Effects search must remain disabled.
   Do not combine `--rebuild` and `--dry-run`. The ordinary dry run does not prove
   that an incompatible table can be written and is not a migration preview.
5. Inspect the final report: account for every invalid item and error rather than
   treating successful process exit as proof of a clean rebuild. Confirm the
   `subject_change` column exists, obsolete `target_change` and
   `deduced_by_inversion` columns are absent, and the ledger uses
   `probabilistic_relations_v3`. Verify source-qualified results in both Effects
   search and CSV export. Test both prevention filters.
6. Re-enable reads and jobs only after these checks pass. Record the revision,
   report, counts and any quarantined invalid source items.

Rebuild uses raw stored responses, never old inverted projection rows. Legacy
missing source qualification becomes `none`; experimental `more`/`less` map to
`increases`/`decreases`, without changing target direction. Old semantic mistakes
remain old semantic mistakes. New prompt text creates a new prompt ID; backfill
alone does not re-extract old papers with Sonnet.

## Recovery

If rebuild fails, keep Effects reads and projection jobs paused. Fix the failure
and rerun the rebuild from intact source datasets. If reverting the application,
restore the compatible derived table/schema (or rebuild it using that revision)
before re-enabling reads. New prevention values are not understood by old
contracts: retain their raw extractions, but isolate them from old projection
code. Reverting code alone is not a safe schema rollback.

## Pilot

Use `openrouter/claude-sonnet-4.6` with the new probabilistic prompt ID. Select
papers not used for prompt development. Run in an isolated dataset first, with
an explicit run ID and recorded source/model/prompt provenance. Cap the paper
and chunk scope; record that a chunk sample is not a full-paper ingestion.

Review source qualifications, target effects, generic process names, participants,
conditions and evidence. Keep accepted claims, rejected claims and uncertain
claims distinct in the pilot report. Do not silently repair quotes or turn
uncertainty into no-effect. A model output passing schema validation is not a
review approval. The follow-up [review gate](review/README.md) now controls Effects visibility and supports bounded model review.

Keep counts descriptive: group on source process, source change, target process
and target effect; count distinct paper IDs, not repeated chunks. Report exact
wording groups as such: synonym resolution is not implemented. A count is not a
probability of truth, and a review citing another paper is not independent evidence
from that original paper. Ranking, automated confidence scoring and bulk rollout
remain separate from this limited pilot.

## Fresh pilot result (2026-09-23)

The frozen prompt in this change was tested on 15 new chunks from five papers
on solitude and wellbeing, excluding every paper in the earlier benchmark.
Selection took the first, middle and last chunk matching stress, depression,
anxiety or wellbeing within each selected paper. This is not full-paper coverage.
The papers were Burger's *Individual Differences in Preference for Solitude*;
Coplan et al.'s *Seeking more solitude*; Nguyen et al.'s *Solitude as an Approach
to Affective Self-Regulation*; and Pauly et al.'s *Social Relationship Quality
Buffers Negative Affective Correlates of Everyday Solitude* and *How we Experience
Being Alone*.

Sonnet 4.6, one step, temperature zero, no retries: 15/15 responses passed the
contract and emitted 41 claims. An agent-authored review of every emitted claim
against its supplied chunk classified 18 as text-supported, 12 as rejected, and
11 as uncertain. Six evidence quotations were not exact source substrings;
15 claims passed both semantic review and exact-quote checks. This is not an
independent expert evaluation, a causal validation, or a recall measurement.
Six chunks emitted no claims; omitted findings were not exhaustively annotated.

Saved responses were replayed without additional API calls through local
extraction persistence and projection: 15 succeeded extractions, 41 projected
relations, zero projection validation errors. All unreviewed outputs remain in
that isolated raw dataset; review labels and eligible groups are separate local
artifacts. Production was not written. Estimated uncached list-price cost was
USD 0.209622, not a billed-cost measurement.

Observed failures include treating lesser increases as prevention, treating
non-significance as no effect, missing source qualification, extracting research
intent as a finding, flattening moderation or essential conditions, using
substances as process endpoints, and repairing OCR/punctuation in evidence.
The prompt already forbids several of these; stronger wording alone is not a
validated fix. The earlier synthetic-control pass did not generalize to these
natural passages.

Decision: this representation can proceed to supervised use, but unattended
bulk extraction should remain off. Next acceptance work is an explicit review
gate, exact evidence-span validation, and regression cases derived from these
failures, followed by a separately held-out paper evaluation. Any such gate must
keep abstention distinct from no-effect. The follow-up [review gate](review/README.md) implements that gate; it does not
claim an exhaustive BFO representation. Do not silently replace the evaluated
prompt and reuse these results as evidence for the replacement.
