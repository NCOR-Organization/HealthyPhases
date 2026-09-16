"""Protobuf is the command and publication schema source of truth."""

from importlib.resources import files

import protovalidate
from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
    json_format,
    message_factory,
)

_POOL = descriptor_pool.DescriptorPool()
for _file in descriptor_pb2.FileDescriptorSet.FromString(
    files(__package__).joinpath("pubmed_publication.pb").read_bytes()
).file:
    _POOL.Add(_file)


def message_type(name):
    return message_factory.GetMessageClass(
        _POOL.FindMessageTypeByName(f"pubmed.v1.{name}")
    )


def validate(name, payload):
    message = message_type(name)()
    try:
        json_format.ParseDict(payload, message)
        protovalidate.validate(message)
    except (json_format.ParseError, protovalidate.ValidationError) as exc:
        raise ValueError(str(exc)) from exc
    return json_format.MessageToDict(
        message,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
    )
