"""Validate JSON commands using the checked-in Protobuf contract."""

from importlib.resources import files
from typing import Any

import protovalidate
from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
    json_format,
    message_factory,
)
from google.protobuf.message import Message

from phases_v2.app import contracts

_POOL = descriptor_pool.DescriptorPool()
for _file in descriptor_pb2.FileDescriptorSet.FromString(
    files(contracts).joinpath("app_resources.pb").read_bytes()
).file:
    _POOL.Add(_file)


def validate_command(name: str, payload: dict[str, Any]) -> Message:
    message = message_factory.GetMessageClass(
        _POOL.FindMessageTypeByName(f"phases_v2.app.v1.{name}")
    )()
    try:
        json_format.ParseDict(payload, message)
        protovalidate.validate(message)
    except protovalidate.ValidationError as invalid:
        # Name each field and rule, so the user can see what to change.
        details = [
            f"{_field_path(v.field.elements)}: {v.message}".lstrip(": ")
            for v in invalid.to_proto().violations
        ]
        raise ValueError("; ".join(details) or str(invalid)) from invalid
    except json_format.ParseError as invalid:
        raise ValueError(str(invalid)) from invalid
    return message


def _field_path(elements) -> str:
    return ".".join(
        f"{e.field_name}[{e.subscript.value}]" if e.subscript else e.field_name
        for e in elements
    )
