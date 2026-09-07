"""Content-addressed identifiers for every row the pipeline writes.

One id does four jobs: dataset primary key, vector id, the local name of an RDF
URI, and the Dagster run key for a request. That is what lets each stage be
idempotent without coordinating anything — re-running derives the same ids and
upserts over its own rows.

Every id is therefore restricted to characters that are safe in all four
places: letters, digits, underscore and hyphen.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")
_SHORT = 12


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _join(*parts: str) -> str:
    """Length-delimit before joining.

    Plain concatenation lets ("ab", "c") and ("a", "bc") collide. Prefixing
    each part with its length makes the encoding unambiguous whatever the
    parts contain, rather than relying on a separator they happen to avoid.
    """
    return "|".join(f"{len(part)}:{part}" for part in parts)


def _slug(value: str) -> str:
    """A readable, URI-safe stem for ids a human will read in a dataset."""
    cleaned = _UNSAFE.sub("-", value.strip()).strip("-_")
    return cleaned or "unnamed"


def paper_id(content: bytes) -> str:
    """Identity of a paper is its content, so the same file found at two
    locations is one paper and is never extracted twice."""
    return _sha256(content)


def chunker_id(name: str, version: str, params: dict[str, Any]) -> str:
    """Changing any parameter yields a new chunker, and therefore new chunks.

    That is deliberate: chunks produced under different settings are not
    interchangeable, so they must not share an identity.
    """
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    digest = _sha256(_join(name, version, canonical).encode())[:_SHORT]
    return f"{_slug(name)}_{_slug(version)}_{digest}"


def chunk_id(paper: str, chunker: str, seq: int) -> str:
    return _sha256(_join(paper, chunker, str(seq)).encode())


def prompt_id(name: str, template: str) -> str:
    """Editing a template's text produces a new id, so work done under the old
    text stays attributable to the exact text that produced it."""
    return f"{_slug(name)}_{_sha256(template.encode())[:_SHORT]}"


def prompt_sha256(template: str) -> str:
    return _sha256(template.encode())


def extraction_id(chunk: str, model: str, prompt: str) -> str:
    """The unit of work: one chunk, one model, one prompt version."""
    return _sha256(_join(chunk, model, prompt).encode())


def item_id(extraction: str, seq: int) -> str:
    return _sha256(_join(extraction, str(seq)).encode())
