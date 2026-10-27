"""The prompt templates this module declares.

Text lives in ``templates/*.txt`` rather than inline: these prompts contain JSON
examples full of braces and quotes, which are unreadable once escaped into
Python string literals.

The text in those files is exactly what is sent to the model, with
``{chunk_text}`` substituted. That matters because the template is also what
gets stored against every extraction — provenance is worthless if the recorded
template is not the one the model saw.

Ported from ``phases``'s ``GenericChunkExtractionWorkflow`` and
``ProcessDispositionExtractionWorkflow``. Those rendered with ``str.format``,
so their braces were doubled; the copies here are un-doubled to match what the
model actually received.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from phases_v2.prompts.domain import PromptTemplate

_DIR = Path(__file__).parent / "templates"

# (prompt name, file stem, output key) — the key the model is asked to return
# its list under.
#
# `conditional_statement` is declared twice, as two versions of one prompt: the
# current text, and the earlier wording the prompt had when it was called
# `logical_sentences`. The earlier version carries the extractions made before
# the rename, so its text must stay byte-for-byte what the model received (its
# id is a hash of that text). That wording asks for its answer under the old
# key, which `extraction.interfaces.LEGACY_OUTPUT_KEYS` still accepts.
_DECLARED: tuple[tuple[str, str, str], ...] = (
    ("solitude_what", "solitude_what", "what"),
    ("solitude_causes", "solitude_causes", "causes"),
    ("solitude_how", "solitude_how", "how"),
    ("solitude_when", "solitude_when", "when"),
    ("solitude_where", "solitude_where", "where"),
    ("solitude_effects", "solitude_effects", "effects"),
    ("conditional_statement", "conditional_statement", "conditional_statement"),
    ("conditional_statement", "conditional_statement_v1", "conditional_statement"),
    ("probabilistic_processes", "probabilistic_processes", "relations"),
)


@lru_cache(maxsize=1)
def declared_prompts() -> tuple[PromptTemplate, ...]:
    return tuple(
        PromptTemplate(
            name=name,
            template=(_DIR / f"{stem}.txt").read_text(),
            output_key=output_key,
        )
        for name, stem, output_key in _DECLARED
    )
