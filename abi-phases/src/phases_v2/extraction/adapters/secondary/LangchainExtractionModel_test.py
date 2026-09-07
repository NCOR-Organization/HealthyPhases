"""The LangChain adapter, held to the shared model contract."""

import pytest

from phases_v2.extraction.adapters.secondary.LangchainExtractionModel import (
    LangchainExtractionModel,
)
from phases_v2.extraction.interfaces import ModelFailed
from phases_v2.extraction.tests.extraction_model__secondary_adapter__generic_test import (
    ExtractionModelContract,
)


class _Message:
    def __init__(self, content):
        self.content = content


class _StubChat:
    def __init__(self, content="{}"):
        self._content = content
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return _Message(self._content)


class _BrokenChat:
    def invoke(self, prompt):
        raise RuntimeError("upstream 503")


class TestLangchainExtractionModel(ExtractionModelContract):
    @pytest.fixture
    def model(self):
        return LangchainExtractionModel(_StubChat('{"results": []}'))

    @pytest.fixture
    def failing_model(self):
        return LangchainExtractionModel(_BrokenChat())

    def test_the_prompt_reaches_the_chat_model_unchanged(self):
        chat = _StubChat('{"results": []}')

        LangchainExtractionModel(chat).complete("Find claims in the text")

        assert chat.prompts == ["Find claims in the text"]

    def test_content_parts_are_joined_into_one_string(self):
        chat = _StubChat([{"text": "part one "}, {"text": "part two"}])

        assert (
            LangchainExtractionModel(chat).complete("x") == "part one part two"
        )

    def test_a_blank_response_is_a_failure_not_an_empty_success(self):
        # An empty string would be recorded as a successful extraction whose
        # response could never be parsed.
        with pytest.raises(ModelFailed, match="empty response"):
            LangchainExtractionModel(_StubChat("   ")).complete("x")

    def test_the_provider_error_is_preserved_in_the_message(self):
        with pytest.raises(ModelFailed, match="503"):
            LangchainExtractionModel(_BrokenChat()).complete("x")
