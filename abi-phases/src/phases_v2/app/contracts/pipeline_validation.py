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
for _file in descriptor_pb2.FileDescriptorSet.FromString(
    files(contracts).joinpath("pipeline_management.pb").read_bytes()
).file:
    _POOL.Add(_file)


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
