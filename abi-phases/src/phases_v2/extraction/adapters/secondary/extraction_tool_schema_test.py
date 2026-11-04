"""What the model is asked for is pinned; what is accepted is wider.

Accepting longer answers must not change what any model receives: the tool
schema sent with every call, and the prompt texts (whose hash is the prompt id,
so a change would make every chunk outstanding again).
"""

import json

import pytest

from phases_v2.extraction.adapters.secondary.extraction_tool_schema import (
    _ACCEPT_POOL,
    _ASK_POOL,
    _PACKAGE,
    ACCEPTED_MAX_ITEMS,
    ACCEPTED_MAX_LEN,
    ExtractionToolSchema,
    InvalidArguments,
    _field_rules,
)
from phases_v2.prompts.templates import declared_prompts

_TOOL = (
    '{"type": "function", "function": {"name": "submit_extraction", '
    '"description": "Submit the claims extracted from the provided text.", '
    '"parameters": PARAMETERS}}'
)


def _listed(key: str) -> str:
    return (
        '{"type": "object", "properties": {"KEY": {"type": "array", "items": '
        '{"type": "string", "minLength": 1}, "maxItems": 10}}, "required": '
        '["KEY"], "additionalProperties": false}'
    ).replace("KEY", key)


_RELATIONS = (
    '{"type": "object", "properties": {"relations": {"type": "array", "items": '
    '{"type": "object", "properties": {'
    '"subject_process": {"type": "string", "minLength": 1}, '
    '"subject_participant": {"type": "string", "minLength": 1}, '
    '"target_process": {"type": "string", "minLength": 1}, '
    '"direction": {"type": "string", "enum": ["increases", "decreases", "no-effect"]}, '
    '"evidence_text": {"type": "string", "minLength": 1, "maxLength": 200}}, '
    '"required": ["subject_process", "subject_participant", "target_process", '
    '"direction", "evidence_text"], "additionalProperties": false}, "maxItems": 8}}, '
    '"required": ["relations"], "additionalProperties": false}'
)

SENT_TO_THE_MODEL = {
    key: _TOOL.replace("PARAMETERS", _listed(key))
    for key in (
        "results",
        "what",
        "causes",
        "how",
        "when",
        "where",
        "effects",
        "conditional_statement",
    )
} | {"relations": _TOOL.replace("PARAMETERS", _RELATIONS)}

# The current version of every declared prompt, and the earlier versions that
# are still declared. Their results are found by these ids.
PROMPT_IDS = {
    "solitude_what_bd3c4b6de030",
    "solitude_causes_f240dcd5f927",
    "solitude_how_defd55d659be",
    "solitude_when_dffb22ac3cdc",
    "solitude_where_eadbe78f900c",
    "solitude_effects_03b778eb43f1",
    "conditional_statement_06c299d1b873",
    "conditional_statement_1624d6b1d2f8",
    "probabilistic_processes_023d15a2ea4a",
}


@pytest.mark.parametrize("output_key", sorted(SENT_TO_THE_MODEL))
def test_the_tool_schema_sent_to_the_model_is_unchanged(output_key):
    tool = ExtractionToolSchema(output_key).tool
    assert json.dumps(tool) == SENT_TO_THE_MODEL[output_key]


def test_every_declared_prompt_has_a_pinned_tool_schema():
    assert {prompt.output_key for prompt in declared_prompts()} <= set(
        SENT_TO_THE_MODEL
    )


def test_prompt_ids_are_unchanged():
    assert {prompt.prompt_id for prompt in declared_prompts()} == PROMPT_IDS


def test_prompts_still_ask_for_the_stricter_limits():
    texts = {prompt.name: prompt.template for prompt in declared_prompts()}
    assert "<= 200 characters" in texts["probabilistic_processes"]
    assert "0 to 8" in texts["probabilistic_processes"]
    assert "0 to 10" in texts["conditional_statement"]


def test_the_accepted_limits_are_wider_than_the_asked_ones():
    assert ACCEPTED_MAX_LEN == 500
    assert ACCEPTED_MAX_ITEMS == 30
    schema = ExtractionToolSchema("relations")
    relation = {
        "subject_process": "a",
        "subject_participant": "b",
        "target_process": "c",
        "direction": "no-effect",
        "evidence_text": "x" * 500,
    }
    schema.validate({"relations": [relation] * 30})
    with pytest.raises(InvalidArguments, match="length 501 exceeds 500"):
        schema.validate({"relations": [relation | {"evidence_text": "x" * 501}]})


def _limits(pool):
    """Every (message.field, rule, limit) of the output package in ``pool``."""
    found = []

    def walk(message):
        for field in message.fields:
            rules = _field_rules(field)
            for kind, string in (
                ("max_len", rules.string),
                ("max_len", rules.repeated.items.string),
            ):
                if string.HasField("max_len"):
                    found.append((f"{message.name}.{field.name}", kind, string.max_len))
            if rules.repeated.HasField("max_items"):
                found.append(
                    (
                        f"{message.name}.{field.name}",
                        "max_items",
                        rules.repeated.max_items,
                    )
                )
        for nested in message.nested_types:
            walk(nested)

    file = pool.FindFileContainingSymbol(f"{_PACKAGE}.RelationsOutput")
    for message in file.message_types_by_name.values():
        walk(message)
    return found


def test_every_accepted_limit_is_at_least_the_accepted_value():
    asked = _limits(_ASK_POOL)
    accepted = _limits(_ACCEPT_POOL)
    assert [(name, kind) for name, kind, _ in accepted] == [
        (name, kind) for name, kind, _ in asked
    ]
    assert len(accepted) == 10  # 9 list limits and the evidence length
    floor = {"max_len": ACCEPTED_MAX_LEN, "max_items": ACCEPTED_MAX_ITEMS}
    for (name, kind, limit), (_, _, ask) in zip(accepted, asked):
        assert limit >= max(floor[kind], ask), name
