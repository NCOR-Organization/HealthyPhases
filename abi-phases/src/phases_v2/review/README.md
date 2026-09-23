# Effects review gate

Extraction and projection retain raw claims. Effects search, counts, pagination
and Effects CSV require the latest review to approve the exact current claim,
raw item, source chunk and provenance. Keyword and semantic search remain
explicitly labeled raw extraction views. Approval is not proof of causation.

Missing reviews, rejected/uncertain decisions, changed inputs, missing exact
evidence, failed extractions and conflicting concurrent decisions fail closed.
Quotation matching is literal: no OCR repair, punctuation/whitespace normalization
or truncation. Correcting a claim requires a new extraction, not a review edit.

## Bounded automatic review

After ingestion/projection:

```sh
uv run abi run script src/phases_v2/review/review_cli.py -- auto --model openrouter/claude-sonnet-4.6 --limit 25
```

This examines at most 25 relations and makes at most one call per pending
relation passing hard checks. Default limit: 100; maximum: 200. It does not loop
through the corpus. Continue using the reported `next_after` with `--after`.
Only pending or changed relations consume this page budget; previously reviewed unchanged claims are skipped. This command does not enable
scheduled paid calls or change extraction models. The selected catalog model
must support explicit timeout and retry controls: temperature zero, 120-second
request timeout, zero retries. A separate invocation of the same model is allowed;
it is not an independently trained reviewer.

All six checks must pass: source qualification, target direction, asserted
finding, generic endpoints, conditions and participants. Provider failures or
malformed tool responses cannot approve. Failed calls are recorded as uncertain,
reported as errors and produce a nonzero CLI exit; no silent retries. Hard
evidence failures are rejected without a model call.

Conservative automatic holds override a model approval to uncertain for flagged
source qualification, temporal-context loss, combined endpoints, age comparisons,
attenuation/moderation, ambiguous null results, and questionable generic process
endpoints. These rules intentionally can withhold valid claims too. A person can
resolve an uncertain claim after inspecting it; hard evidence blockers cannot
be overridden. Model confidence is not used to bypass either kind of check.

Source text is untrusted data in a separate user message; review instructions
are a system message. The only tool submits a verdict. This does not guarantee
protection against prompt injection or semantic errors. Evaluate on fresh held-out
papers before enabling unattended high-volume runs.

To run a bounded review automatically after the pipeline projects relations,
set these module configuration values explicitly:

```yaml
effects_review_model: openrouter/claude-sonnet-4.6
effects_review_limit: 25
```

The default model is empty (no scheduled model calls). The gate itself is always
active. Pipeline reviews use the same selected paper scope as ingestion. Claims
beyond the per-run limit stay pending; the result includes a continuation cursor.
Review-provider errors fail the pipeline stage while preserving extracted data
and recorded decisions. A retry skips already reviewed unchanged claims.

## Inspect, override or revoke

```sh
uv run abi run script src/phases_v2/review/review_cli.py -- export --output /tmp/effects-review.html --limit 100
```

Open the HTML in Firefox to inspect claims, source text, flags, blockers, previous
decisions and notes. Select decisions, enter reasons and a reviewer name, then
download the decisions JSON. Flags are reminders, not an exhaustive classifier.

```sh
uv run abi run script src/phases_v2/review/review_cli.py -- apply --decisions /path/to/effect-decisions.json
```

Protobuf/Protovalidate validates the batch. The claim fingerprint and previous
event ID are checked again before writing. Stale pages cannot override newer
decisions. Reject or mark uncertain to revoke approval. A stale batch fails
before any of its decisions are written. Concurrent sibling events are retained
and deny visibility until a fresh decision resolves them. Storage errors surface.
Decision files apply once; replay is stale.

Commands use existing dataset permissions. Reviewer names are operator assertions,
not authenticated identities. There is no new public approval HTTP endpoint.
Multi-user authenticated review remains separate work.

## Storage and rollout

The additive `effect_reviews` dataset uses the existing RowStore and adapter.
Startup creates it through `ensure_datasets`, without changing existing tables.
Include it in backups. Each audit event retains an ID, timestamp, previous event,
fingerprint, policy, reviewer kind and note. Model events also retain the model
ID, full review prompt and raw response. No confidence score is generated.

Existing relations start unreviewed, so Effects may initially be empty. A missing
or unavailable review dataset errors rather than exposing raw claims. Create the
dataset before serving queries. Deployments before PR 83 still need that PR's
qualified-effects schema rebuild.

Audit events survive relation rebuilds: unchanged content retains approval;
changed content/provenance requires review. Effects requests and exports require
the current dataset snapshot. Old snapshots return HTTP 409 to prevent restoring
revoked approval. An already-started request observes its pinned snapshot.

Increment `POLICY` when changing hard approval requirements or fingerprint format.
Prompt text is retained per event, but changing it alone does not retroactively
invalidate approvals. Bump policy and run bounded batches to require re-review.
Raw graph/vector projections are not promoted to reviewed evidence by this gate.
Rolling back to code without the gate exposes raw Effects results again; keep
Effects unavailable during rollback until that policy is deliberately resolved.
This change has not been deployed to production.

## Evaluation

Offline tests cover hard evidence checks, all six model checks, malformed verdicts,
provider failure, stale inputs, audit history, concurrent conflicts, revocation,
search/export and snapshots. The original five-paper pilot is a development
regression set, not a held-out accuracy benchmark. Its agent-authored labels are
not independent expert adjudication.


### Development regression result (2026-09-23)

The reviewer made 35 paid calls on the 41 saved pilot claims; six failed exact
quote checks without a call. Its initial verdicts were 16 approved, 20 rejected,
and five uncertain. Comparison with the earlier agent review found one rejected
and four uncertain claims among those approvals. The added conservative holds
were then tested by replaying saved verdicts on identical claims/chunks, preserving
the original model prompts and responses, with zero additional paid calls.

Final gate: 10 approved, 20 rejected, 11 uncertain. Actual local Effects search
returned exactly those 10 approvals. All 12 previously rejected claims stayed
excluded, and all 10 approvals were among the 15 claims previously marked both
text-supported and exact-quoted. Five of those 15 remain withheld: this is a
conservative development result, not a recall score or proof of generalization.
Estimated uncached list-price review cost was USD 0.4488, not billed cost.
A fresh held-out evaluation is still required before expanding automatic use.
