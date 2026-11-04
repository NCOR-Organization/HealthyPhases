"""Derive tool schemas and validators from the checked-in Protobuf descriptor.

What we *ask* for and what we *accept* are kept apart on purpose:

- ``extraction_output.proto`` states what we ask for. The tool schema sent with
  every call is derived from it, and the prompt texts state the same limits.
  Changing it changes what the model receives.
- :data:`ACCEPTED_MAX_LEN` and :data:`ACCEPTED_MAX_ITEMS` state how far past a
  length or count limit an answer may go and still be kept. Validation runs the
  proto's own rules from a copy of the descriptor in which every ``max_len`` and
  ``max_items`` is raised to these values; every other rule (allowed values,
  non-empty strings, exact keys, list shapes) is the proto's, unchanged.

A model asked for at most 200 characters that writes 230 has still answered
the question; rejecting that costs a call and loses the answer.

Only the string, repeated and message rules used by extraction_output.proto
are mapped here. Semantic grounding remains the model's responsibility.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

import protovalidate
from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
    json_format,
    message_factory,
)

from phases_v2.extraction import contracts

# The most an answer may hold, whatever the proto asks for. A limit the proto
# already sets higher is kept.
ACCEPTED_MAX_LEN = 500
ACCEPTED_MAX_ITEMS = 30

_PACKAGE = "phases_v2.extraction.v1"
# How many rule failures one error spells out before summarising the rest.
_SHOWN_VIOLATIONS = 3

_DESCRIPTOR = descriptor_pb2.FileDescriptorSet.FromString(
    files(contracts).joinpath("extraction_output.pb").read_bytes()
)


def _pool(descriptor_set: descriptor_pb2.FileDescriptorSet):
    pool = descriptor_pool.DescriptorPool()
    for file in descriptor_set.file:
        pool.Add(file)
    return pool


# What we ask for: the descriptor exactly as checked in.
_ASK_POOL = _pool(_DESCRIPTOR)
_OPTIONS = message_factory.GetMessageClass(
    _ASK_POOL.FindMessageTypeByName("google.protobuf.FieldOptions")
)
_RULES = _ASK_POOL.FindExtensionByName("buf.validate.field")


def _field_rules(field) -> Any:
    return _OPTIONS.FromString(field.GetOptions().SerializeToString()).Extensions[
        _RULES
    ]


def _messages(messages):
    """Every message in ``messages``, nested ones included."""
    for message in messages:
        yield message
        yield from _messages(message.nested_type)


def _relaxed(descriptor_set: descriptor_pb2.FileDescriptorSet):
    """A copy of ``descriptor_set`` with its length and count limits raised."""
    relaxed = descriptor_pb2.FileDescriptorSet()
    relaxed.CopyFrom(descriptor_set)
    for file in relaxed.file:
        if file.package != _PACKAGE:
            continue
        for message in _messages(file.message_type):
            for field in message.field:
                options = _OPTIONS.FromString(field.options.SerializeToString())
                if not options.HasExtension(_RULES):
                    continue
                rules = options.Extensions[_RULES]
                for string in (rules.string, rules.repeated.items.string):
                    if string.HasField("max_len"):
                        string.max_len = max(string.max_len, ACCEPTED_MAX_LEN)
                if rules.repeated.HasField("max_items"):
                    rules.repeated.max_items = max(
                        rules.repeated.max_items, ACCEPTED_MAX_ITEMS
                    )
                field.options.Clear()
                field.options.MergeFromString(options.SerializeToString())
    return relaxed


# What we accept: the same messages under the raised limits.
_ACCEPT_POOL = _pool(_relaxed(_DESCRIPTOR))


class UnknownOutput(ValueError):
    """No output message is declared for this output key."""


class InvalidArguments(ValueError):
    """The tool arguments break a rule; the message names the field and rule."""


def _string_schema(rules):
    schema = {"type": "string"}
    if rules.HasField("min_len"):
        schema["minLength"] = rules.min_len
    if rules.HasField("max_len"):
        schema["maxLength"] = rules.max_len
    if getattr(rules, "in"):
        schema["enum"] = list(getattr(rules, "in"))
    return schema


def _object_schema(descriptor):
    properties = {}
    for field in descriptor.fields:
        rules = _field_rules(field)
        if field.message_type is not None:
            schema = _object_schema(field.message_type)
        elif field.is_repeated:
            schema = _string_schema(rules.repeated.items.string)
        else:
            schema = _string_schema(rules.string)
        if field.is_repeated:
            schema = {"type": "array", "items": schema}
            if rules.repeated.HasField("max_items"):
                schema["maxItems"] = rules.repeated.max_items
        properties[field.name] = schema
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _path(field_path) -> str:
    """``relations[2].evidence_text`` from a Protovalidate field path."""
    text = ""
    for element in field_path.elements:
        text += f".{element.field_name}" if text else element.field_name
        subscript = getattr(element, "subscript", None)
        if subscript is not None and subscript.field == "index":
            text += f"[{subscript.value}]"
    return text


def _describe(violation) -> str:
    proto = violation.proto
    rule = proto.rule_id
    value, limit = violation.field_value, violation.rule_value
    if rule == "string.max_len":
        detail = f"length {len(value)} exceeds {limit}"
    elif rule == "string.min_len":
        detail = "is empty" if not value else f"length {len(value)} is below {limit}"
    elif rule == "repeated.max_items":
        detail = f"{len(value)} items exceed {limit}"
    elif rule == "string.in":
        detail = f"{value!r} is not one of {', '.join(limit)}"
    else:
        detail = f"{proto.message} ({rule})"
    return f"{_path(proto.field)}: {detail}"


def _summary(problems: list[str]) -> str:
    shown = "; ".join(problems[:_SHOWN_VIOLATIONS])
    rest = len(problems) - _SHOWN_VIOLATIONS
    return f"{shown}; and {rest} more" if rest > 0 else shown


class ExtractionToolSchema:
    def __init__(self, output_key: str):
        name = "".join(part.title() for part in output_key.split("_")) + "Output"
        try:
            descriptor = _ASK_POOL.FindMessageTypeByName(f"{_PACKAGE}.{name}")
        except KeyError as failure:
            raise UnknownOutput(f"No extraction schema for {output_key!r}") from failure
        self._name = name
        self._message = message_factory.GetMessageClass(
            _ACCEPT_POOL.FindMessageTypeByName(f"{_PACKAGE}.{name}")
        )
        # Sent to the model: derived from the proto as checked in, so it asks
        # for the stricter limits.
        self.parameters = _object_schema(descriptor)
        self.tool = {
            "type": "function",
            "function": {
                "name": "submit_extraction",
                "description": "Submit the claims extracted from the provided text.",
                "parameters": self.parameters,
            },
        }

    def validate(self, arguments: Any) -> None:
        """Raise :class:`InvalidArguments` unless ``arguments`` is acceptable.

        Protobuf permits absent/default fields and JSON coercions. Check the
        exact tool shape first, then execute the proto rules under the accepted
        limits.
        """
        problems: list[str] = []
        self._check_shape(arguments, self.parameters, "", problems)
        if not problems:
            message = json_format.ParseDict(arguments, self._message())
            try:
                protovalidate.validate(message)
            except protovalidate.ValidationError as failure:
                problems = [_describe(v) for v in failure.violations]
                if not problems:
                    raise InvalidArguments(f"invalid {self._name}") from failure
        if problems:
            raise InvalidArguments(f"invalid {self._name}: {_summary(problems)}")

    @classmethod
    def _check_shape(cls, value, schema, path: str, problems: list[str]) -> None:
        where = path or "arguments"
        kind = schema["type"]
        if kind == "object":
            if not isinstance(value, dict):
                problems.append(f"{where}: must be an object")
                return
            missing = [key for key in schema["required"] if key not in value]
            unexpected = sorted(
                str(key) for key in value if key not in schema["required"]
            )
            if missing:
                problems.append(f"{where}: missing field(s) {', '.join(missing)}")
            if unexpected:
                problems.append(f"{where}: unexpected field(s) {', '.join(unexpected)}")
            for key, child in schema["properties"].items():
                if key in value:
                    cls._check_shape(
                        value[key], child, f"{path}.{key}" if path else key, problems
                    )
        elif kind == "array":
            if not isinstance(value, list):
                problems.append(f"{where}: must be a list")
                return
            for index, item in enumerate(value):
                cls._check_shape(item, schema["items"], f"{where}[{index}]", problems)
        elif not isinstance(value, str):
            problems.append(f"{where}: must be a string")
