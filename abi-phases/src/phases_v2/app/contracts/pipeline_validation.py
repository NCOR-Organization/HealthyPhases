"""Load the generated descriptor and execute its authoritative validation."""

from importlib.resources import files

import protovalidate
from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
    json_format,
    message_factory,
)

from phases_v2.app import contracts

_POOL = descriptor_pool.DescriptorPool()
_ADDED: set[str] = set()
for _descriptor in (
    "pipeline_management.pb",
    "search.pb",
    "prompt_playground.pb",
    "paper_results.pb",
):
    for _file in descriptor_pb2.FileDescriptorSet.FromString(
        files(contracts).joinpath(_descriptor).read_bytes()
    ).file:
        # Each set carries its own copy of the shared imports; the first wins.
        if _file.name not in _ADDED:
            _POOL.Add(_file)
            _ADDED.add(_file.name)


def validate_message(name: str, payload: dict) -> dict:
    message = message_factory.GetMessageClass(
        _POOL.FindMessageTypeByName(f"phases_v2.app.v1.{name}")
    )()
    try:
        json_format.ParseDict(payload, message)
        protovalidate.validate(message)
    except protovalidate.ValidationError as invalid:
        details = [
            f"{'.'.join(part.field_name for part in v.field.elements)}: {v.message}"
            for v in invalid.to_proto().violations
        ]
        raise ValueError("; ".join(details)) from invalid
    except json_format.ParseError as invalid:
        raise ValueError(str(invalid)) from invalid
    return payload
