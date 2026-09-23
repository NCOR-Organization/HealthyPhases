"""Authoritative Protovalidate boundary for operator decisions."""

from importlib.resources import files

import protovalidate
from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
    json_format,
    message_factory,
)

from phases_v2.review import contracts

_POOL = descriptor_pool.DescriptorPool()
for _file in descriptor_pb2.FileDescriptorSet.FromString(
    files(contracts).joinpath("review.pb").read_bytes()
).file:
    _POOL.Add(_file)
_MESSAGE = message_factory.GetMessageClass(
    _POOL.FindMessageTypeByName("phases_v2.review.v1.ReviewBatch")
)
MODEL_MESSAGE = message_factory.GetMessageClass(
    _POOL.FindMessageTypeByName("phases_v2.review.v1.ModelReview")
)


def validate_batch(payload: dict) -> None:
    validate(payload, _MESSAGE)


def validate(payload: dict, message_type=MODEL_MESSAGE) -> None:
    try:
        protovalidate.validate(json_format.ParseDict(payload, message_type()))
    except (protovalidate.ValidationError, json_format.ParseError) as error:
        raise ValueError(str(error)) from error
