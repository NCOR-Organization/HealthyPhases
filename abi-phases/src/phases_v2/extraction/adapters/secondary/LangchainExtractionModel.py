"""Extract validated arguments from one forced LangChain tool call."""

from __future__ import annotations

import json
from typing import Any

from phases_v2.extraction.adapters.secondary.extraction_tool_schema import (
    ExtractionToolSchema,
)
from phases_v2.extraction.interfaces import ModelFailed


class LangchainExtractionModel:
    def __init__(self, chat_model: Any, output_key: str = "results"):
        self._schema = ExtractionToolSchema(output_key)
        self._chat_model = chat_model.bind_tools(
            [self._schema.tool],
            tool_choice="submit_extraction",
            parallel_tool_calls=False,
        )

    def complete(self, prompt: str) -> str:
        if not prompt.strip():
            raise ModelFailed("refusing to send an empty prompt")

        raw = None
        try:
            response = self._chat_model.invoke(prompt)
            raw = response.model_dump_json()
            calls = response.tool_calls
            if response.invalid_tool_calls or len(calls) != 1:
                raise ValueError("expected exactly one valid extraction tool call")
            call = calls[0]
            if call["name"] != "submit_extraction":
                raise ValueError("model called an unexpected tool")
            self._schema.validate(call["args"])
            # Keep the existing string port and stored response shape. The body
            # comes only from validated tool arguments, never message prose.
            return json.dumps(call["args"], ensure_ascii=False)
        except Exception as failure:  # One provider failure costs one chunk.
            raise ModelFailed(
                f"extraction tool call failed: {failure}", raw_response=raw
            ) from failure
