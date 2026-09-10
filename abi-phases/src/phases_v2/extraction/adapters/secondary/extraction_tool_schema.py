"""Derive tool schemas and validators from the checked-in Protobuf descriptor.

Only the string, repeated and message rules used by extraction_output.proto
are mapped here. Semantic grounding remains the model's responsibility.
"""

from importlib.resources import files

import protovalidate
from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
    json_format,
    message_factory,
)

from phases_v2.extraction import contracts

_POOL = descriptor_pool.DescriptorPool()
_DESCRIPTOR = descriptor_pb2.FileDescriptorSet.FromString(
    files(contracts).joinpath("extraction_output.pb").read_bytes()
)
for _file in _DESCRIPTOR.file:
    _POOL.Add(_file)
_OPTIONS = message_factory.GetMessageClass(
    _POOL.FindMessageTypeByName("google.protobuf.FieldOptions")
)
_RULES = _POOL.FindExtensionByName("buf.validate.field")


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
        rules = _OPTIONS.FromString(field.GetOptions().SerializeToString()).Extensions[
            _RULES
        ]
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


class ExtractionToolSchema:
    def __init__(self, output_key: str):
        name = "".join(part.title() for part in output_key.split("_")) + "Output"
        try:
            descriptor = _POOL.FindMessageTypeByName(f"phases_v2.extraction.v1.{name}")
        except KeyError as failure:
            raise ValueError(f"No extraction schema for {output_key!r}") from failure
        self._message = message_factory.GetMessageClass(descriptor)
        self.parameters = _object_schema(descriptor)
        self.tool = {
            "type": "function",
            "function": {
                "name": "submit_extraction",
                "description": "Submit the claims extracted from the provided text.",
                "parameters": self.parameters,
            },
        }

    def validate(self, arguments: dict) -> None:
        # Protobuf permits absent/default fields and JSON coercions. Check the
        # exact tool shape first, then execute the authoritative proto rules.
        self._check_shape(arguments, self.parameters)
        message = json_format.ParseDict(arguments, self._message())
        protovalidate.validate(message)

    @classmethod
    def _check_shape(cls, value, schema):
        kind = schema["type"]
        if kind == "object":
            if not isinstance(value, dict) or set(value) != set(schema["required"]):
                raise ValueError("tool arguments have missing or unexpected fields")
            for key, child in schema["properties"].items():
                cls._check_shape(value[key], child)
        elif kind == "array":
            if not isinstance(value, list):
                raise ValueError("tool argument must be a list")
            for item in value:
                cls._check_shape(item, schema["items"])
        elif not isinstance(value, str):
            raise ValueError("tool argument must be a string")
