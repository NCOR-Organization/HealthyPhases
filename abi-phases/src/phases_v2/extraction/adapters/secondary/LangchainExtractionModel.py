"""A LangChain chat model, as the domain's :class:`ExtractionModel`.

Every provider error is re-raised as :class:`ModelFailed` so one bad call costs
one chunk rather than the run.
"""

from __future__ import annotations

from typing import Any

from phases_v2.extraction.interfaces import ModelFailed


class LangchainExtractionModel:
    def __init__(self, chat_model: Any):
        self._chat_model = chat_model

    def complete(self, prompt: str) -> str:
        if not prompt.strip():
            raise ModelFailed("refusing to send an empty prompt")

        try:
            response = self._chat_model.invoke(prompt)
        except Exception as failure:  # noqa: BLE001 - any provider error is one failed unit
            raise ModelFailed(f"model call failed: {failure}") from failure

        content = getattr(response, "content", response)
        if isinstance(content, list):
            # Some providers return content parts rather than a single string.
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        text = str(content)
        if not text.strip():
            raise ModelFailed("model returned an empty response")
        return text
