"""Extract validated arguments from one forced LangChain tool call."""

from __future__ import annotations

import json
from typing import Any

from phases_v2.extraction.adapters.secondary.extraction_tool_schema import (
    ExtractionToolSchema,
)
from phases_v2.extraction.interfaces import LEGACY_OUTPUT_KEYS, ModelFailed

# Provider SDKs and HTTP clients name the same few conditions differently, so
# these are matched by class name down the MRO rather than importing every
# vendor's exception types into an adapter that is meant to be vendor-neutral.
_TRANSIENT_ERROR_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "ReadError",
        "WriteTimeout",
        "PoolTimeout",
        "RemoteProtocolError",
        "RateLimitError",
        "InternalServerError",
        "OverloadedError",
    }
)
# 408 request timeout, 409 provider-side conflict, 429 rate limit.
_TRANSIENT_STATUSES = frozenset({408, 409, 429})


def is_transient(failure: BaseException) -> bool:
    """Whether the same call could succeed if it were simply made again."""
    if isinstance(failure, (ConnectionError, TimeoutError)):
        return True
    status = getattr(failure, "status_code", None)
    if isinstance(status, int):
        return status in _TRANSIENT_STATUSES or status >= 500
    return any(cls.__name__ in _TRANSIENT_ERROR_NAMES for cls in type(failure).__mro__)


class LangchainExtractionModel:
    def __init__(self, chat_model: Any, output_key: str = "results"):
        self._output_key = output_key
        self._schema = ExtractionToolSchema(output_key)
        self._chat_model = chat_model.bind_tools(
            [self._schema.tool],
            tool_choice="submit_extraction",
            parallel_tool_calls=False,
        )

    def complete(self, prompt: str) -> str:
        if not prompt.strip():
            raise ModelFailed("refusing to send an empty prompt")

        try:
            response = self._chat_model.invoke(prompt)
        except Exception as failure:  # One provider failure costs one chunk.
            raise ModelFailed(
                f"extraction tool call failed: {failure}",
                transient=is_transient(failure),
            ) from failure

        raw = None
        try:
            raw = response.model_dump_json()
            calls = response.tool_calls
            if response.invalid_tool_calls or len(calls) != 1:
                raise ValueError("expected exactly one valid extraction tool call")
            call = calls[0]
            if call["name"] != "submit_extraction":
                raise ValueError("model called an unexpected tool")
            arguments = self._current_key(call["args"])
            self._schema.validate(arguments)
            # Keep the existing string port and stored response shape. The body
            # comes only from validated tool arguments, never message prose.
            return json.dumps(arguments, ensure_ascii=False)
        except Exception as failure:  # One provider failure costs one chunk.
            raise ModelFailed(
                f"extraction tool call failed: {failure}", raw_response=raw
            ) from failure

    def _current_key(self, arguments: Any) -> Any:
        """Accept the answer under a key this output used to be returned as.

        A renamed prompt keeps its earlier wording, which asks for the earlier
        key; a model that follows the wording rather than the tool schema is
        still giving the right answer.
        """
        if not isinstance(arguments, dict) or self._output_key in arguments:
            return arguments
        for legacy in LEGACY_OUTPUT_KEYS.get(self._output_key, ()):
            if set(arguments) == {legacy}:
                return {self._output_key: arguments[legacy]}
        return arguments
