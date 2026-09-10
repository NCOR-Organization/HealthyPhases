# Extraction tool contract

`extraction_output.proto` is the source of truth for tool arguments. Its
Protovalidate annotations are executed locally for every tool response. The
adapter derives the tool JSON Schema from the same descriptor, including list
limits, nonempty strings, direction values, and evidence length. Semantic
requirements (grounding, process wording, and logical sentence phrasing) still
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

Prompt text and IDs remain unchanged to preserve successful-work deduplication.
On rerun, failed rows receive fresh model calls and are overwritten by the usual
upsert. Old failed text is not repaired, and successes are not deleted.
