"""The prompt registry.

Templates are declared in code and published to the ``prompts`` dataset on
start. A template's identity is its text, so editing one produces a new
``prompt_id`` and the extractions made under the old text keep pointing at the
exact text that produced them.

Registration is an upsert with no read of its own. A caller that already
knows which versions exist passes their ids, and those rows are left alone, so
a version's ``registered_at`` stays the time it first appeared rather than the
last engine start.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime

from phases_v2 import identity
from phases_v2.ports import RowStore

CHUNK_PLACEHOLDER = "{chunk_text}"


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    template: str
    output_key: str = "results"

    @property
    def prompt_id(self) -> str:
        return identity.prompt_id(self.name, self.template)

    def rendered_for(self, chunk_text: str) -> str:
        return self.template.replace(CHUNK_PLACEHOLDER, chunk_text)


def validate(templates: list[PromptTemplate]) -> None:
    """Reject a declaration that could never produce an extraction.

    A template with no chunk placeholder would be sent to the model with no
    text in it, so this fails loudly at start rather than producing a run's
    worth of confidently empty results.
    """
    for template in templates:
        if CHUNK_PLACEHOLDER not in template.template:
            raise ValueError(
                f"prompt template {template.name!r} does not contain "
                f"{CHUNK_PLACEHOLDER}, so it would be sent to the model with "
                "no chunk text in it"
            )


def register_prompts(
    store: RowStore,
    templates: list[PromptTemplate],
    *,
    already_registered: Collection[str] = (),
) -> list[str]:
    """Publish every declared template. Returns their ids, in declaration order.

    Templates whose id is in ``already_registered`` are not rewritten.
    """
    validate(templates)
    if not templates:
        return []

    new = [t for t in templates if t.prompt_id not in set(already_registered)]
    if not new:
        return [template.prompt_id for template in templates]
    now = datetime.now(UTC)
    store.write_rows(
        "prompts",
        [
            {
                "prompt_id": template.prompt_id,
                "name": template.name,
                "prompt_sha256": identity.prompt_sha256(template.template),
                "template": template.template,
                "output_key": template.output_key,
                "registered_at": now,
            }
            for template in new
        ],
    )
    return [template.prompt_id for template in templates]
