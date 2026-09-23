"""LangChain adapter: one forced review tool call, no fallback approval."""

from phases_v2.extraction.adapters.secondary.extraction_tool_schema import (
    ExtractionToolSchema,
    _object_schema,
)
from phases_v2.review.contracts.review_validation import MODEL_MESSAGE, validate
from phases_v2.review.review_automation import ReviewFailed


class LangchainReviewModel:
    def __init__(self, chat_model):
        self.parameters = _object_schema(MODEL_MESSAGE.DESCRIPTOR)
        tool = {
            "type": "function",
            "function": {
                "name": "submit_review",
                "description": "Review one extracted claim against source text.",
                "parameters": self.parameters,
            },
        }
        self.model = chat_model.bind_tools(
            [tool], tool_choice="submit_review", parallel_tool_calls=False
        )

    def review(self, instructions, source):
        raw = ""
        try:
            response = self.model.invoke(
                [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": source},
                ]
            )
            raw = response.model_dump_json()
            if response.invalid_tool_calls or len(response.tool_calls) != 1:
                raise ValueError("Expected exactly one valid review tool call")
            call = response.tool_calls[0]
            if call["name"] != "submit_review":
                raise ValueError("Unexpected review tool")
            ExtractionToolSchema._check_shape(call["args"], self.parameters)
            validate(call["args"])
            return call["args"], raw
        except Exception as error:
            raise ReviewFailed(str(error), raw) from error
