# Extraction tool contract

`extraction_output.proto` is the source of truth for tool arguments. Its
Protovalidate annotations are executed locally for every tool response. The
adapter derives the tool JSON Schema from the same descriptor, including list
limits, nonempty strings, direction values, and evidence length. Semantic
requirements (grounding, process wording, and conditional statement phrasing) still
belong to the prompts; shape validation cannot prove them.

`extraction_output.pb` is a checked-in descriptor set, including dependencies.
It is loaded as dynamic Protobuf message classes, avoiding generated import
paths for third-party option definitions. Package data includes both files.
To regenerate, install protoc 29.3 and run `make proto`; the script fetches
Protovalidate v1.0.0's option definitions and checks their SHA-256. No compiler
or network access is needed at runtime. This is the interim code-generation
workflow for this slice; CI does not currently regenerate descriptors.

The adapter supports the string, repeated, and nested-message constraints used
here. Extend its schema mapping and tests when introducing new rule types.
Required keys, exact JSON types, and rejection of unknown keys are checked
before Protobuf parsing, which would otherwise permit defaults/coercions.

A forced `submit_extraction` call supplies the arguments; message prose is
never parsed as extraction output. The adapter validates locally rather than
relying on provider-specific strict-schema support. Successful `raw_response`
contains the serialized validated arguments; failed calls retain the complete
LangChain message when one was returned. There is no silent text fallback.

Prompt IDs derive from prompt text, and successful-work deduplication keys on
them. On rerun, failed rows receive fresh model calls and are overwritten by the
usual upsert. Old failed text is not repaired, and successes are not deleted.
Editing a prompt's text gives it a new ID, so every chunk becomes outstanding
for that prompt again, while extractions made with the old text are kept.

`Relation.subject_change` is required in new tool calls. It is `none` (source
unqualified) or one of the same five effects accepted by `direction`: increases,
decreases, no-effect, prevents-increase, prevents-decrease. Direction is the
single target effect; there is no `target_change` and no sign arithmetic.
The removed target-change field number/name are reserved in Protobuf. The
projection accepts old source amount labels and absent source qualification;
new model responses must use the exact new contract. Shape validation cannot
verify whether prevention, causality, or absence of effect is supported.

Offline regeneration can reuse the dependency descriptors already checked in:
`protoc -I src --descriptor_set_in=<existing extraction_output.pb>
--include_imports --descriptor_set_out=<temporary output.pb> <contract.proto>`.
Replace the corresponding checked-in descriptor after compilation. Regenerate
extraction, projection, and search descriptors together for this change.

Evidence may contain up to 2,000 characters so complete supporting sentences
fit without forced paraphrase or truncation. This is a bounded payload limit,
not an evidence-quality threshold. The prompt text changes with the limit,
producing a new prompt ID. Projection/search preserve full evidence, including
older excerpts. Exact quotation and semantic support require separate checks.
