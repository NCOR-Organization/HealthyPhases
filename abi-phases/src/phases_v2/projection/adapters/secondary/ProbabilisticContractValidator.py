"""Validate derived rows against the versioned Protobuf contract."""

from importlib.resources import files

import protovalidate
from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
    json_format,
    message_factory,
)

from phases_v2.projection import contracts

_POOL = descriptor_pool.DescriptorPool()
for _file in descriptor_pb2.FileDescriptorSet.FromString(
    files(contracts).joinpath("probabilistic.pb").read_bytes()
).file:
    _POOL.Add(_file)
_MESSAGE = message_factory.GetMessageClass(
    _POOL.FindMessageTypeByName("phases_v2.projection.v1.ProbabilisticRelation")
)


def validate_relation(row: dict) -> None:
    try:
        message = json_format.ParseDict(row, _MESSAGE())
        protovalidate.validate(message)
    except (json_format.ParseError, protovalidate.ValidationError) as error:
        raise ValueError(str(error)) from error
