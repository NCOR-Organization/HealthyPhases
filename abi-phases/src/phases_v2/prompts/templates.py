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

# (file stem, output key) — the key the model is asked to return its list under.
_DECLARED: tuple[tuple[str, str], ...] = (
    ("solitude_what", "what"),
    ("solitude_causes", "causes"),
    ("solitude_how", "how"),
    ("solitude_when", "when"),
    ("solitude_where", "where"),
    ("solitude_effects", "effects"),
    ("conditional_statement", "conditional_statement"),
    ("probabilistic_processes", "relations"),
)


@lru_cache(maxsize=1)
def declared_prompts() -> tuple[PromptTemplate, ...]:
    return tuple(
        PromptTemplate(
            name=stem,
            template=(_DIR / f"{stem}.txt").read_text(),
            output_key=output_key,
        )
        for stem, output_key in _DECLARED
    )
