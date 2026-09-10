"""Tool enforcement, contract validation, and provider failures."""

import json

import pytest
from langchain_core.messages import AIMessage

from phases_v2.extraction.adapters.secondary.LangchainExtractionModel import (
    LangchainExtractionModel,
)
from phases_v2.extraction.interfaces import ModelFailed
from phases_v2.extraction.tests.extraction_model__secondary_adapter__generic_test import (
    ExtractionModelContract,
)
from phases_v2.prompts.templates import declared_prompts


def _message(args=None, name="submit_extraction"):
    return AIMessage(
        content="Prose is deliberately ignored.",
        tool_calls=[{"name": name, "args": args or {"results": []}, "id": "call-1"}],
    )


class _StubChat:
    def __init__(self, message=None):
        self.message = message if message is not None else _message()
        self.prompts = []

    def bind_tools(self, tools, **kwargs):
        self.tools = tools
        self.options = kwargs
        return self

    def invoke(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.message, Exception):
            raise self.message
        return self.message


class TestLangchainExtractionModel(ExtractionModelContract):
    @pytest.fixture
    def model(self):
        return LangchainExtractionModel(_StubChat())

    @pytest.fixture
    def failing_model(self):
        return LangchainExtractionModel(_StubChat(RuntimeError("upstream 503")))

    def test_forces_one_tool_and_ignores_prose(self):
        chat = _StubChat(_message({"what": ["Solitude can be restorative."]}))
        model = LangchainExtractionModel(chat, "what")
        assert json.loads(model.complete("Find claims")) == {
            "what": ["Solitude can be restorative."]
        }
        assert chat.prompts == ["Find claims"]
        assert chat.options == {
            "tool_choice": "submit_extraction",
            "parallel_tool_calls": False,
        }
        parameters = chat.tools[0]["function"]["parameters"]
        assert parameters["required"] == ["what"]
        assert parameters["additionalProperties"] is False

    @pytest.mark.parametrize(
        "message",
        [
            AIMessage(content='```json\n{"results": []}\n```'),
            AIMessage(content="", tool_calls=_message().tool_calls * 2),
            _message(name="wrong_tool"),
            AIMessage(
                content="",
                invalid_tool_calls=[
                    {
                        "name": "submit_extraction",
                        "args": "{",
                        "id": "bad",
                        "error": "bad JSON",
                    }
                ],
            ),
        ],
    )
    def test_invalid_calls_fail_and_keep_the_original_message(self, message):
        with pytest.raises(ModelFailed) as caught:
            LangchainExtractionModel(_StubChat(message)).complete("x")
        assert json.loads(caught.value.raw_response) == json.loads(
            message.model_dump_json()
        )

    @pytest.mark.parametrize(
        "args",
        [
            {"wrong": []},
            {"results": None},
            {"results": "text"},
            {"results": [42]},
            {"results": [{}]},
            {"results": [""]},
            {"results": ["x"] * 11},
            {"results": [], "extra": "no"},
        ],
    )
    def test_rejects_invalid_sentence_arguments(self, args):
        with pytest.raises(ModelFailed):
            LangchainExtractionModel(_StubChat(_message(args))).complete("x")

    @pytest.mark.parametrize("prompt", declared_prompts())
    def test_each_declared_prompt_accepts_an_empty_result(self, prompt):
        args = {prompt.output_key: []}
        result = LangchainExtractionModel(
            _StubChat(_message(args)), prompt.output_key
        ).complete("x")
        assert json.loads(result) == args

    def test_provider_error_is_preserved(self):
        with pytest.raises(ModelFailed, match="503"):
            LangchainExtractionModel(_StubChat(RuntimeError("503"))).complete("x")


RELATION = {
    "subject_process": "social isolation",
    "subject_participant": "isolated person",
    "target_process": "experiencing loneliness",
    "direction": "increases",
    "evidence_text": "Social isolation increases loneliness.",
}


def test_valid_relation_is_preserved_as_an_object():
    args = {"relations": [RELATION]}
    model = LangchainExtractionModel(_StubChat(_message(args)), "relations")
    assert json.loads(model.complete("x")) == args


@pytest.mark.parametrize(
    "changes",
    [
        {"direction": "perhaps"},
        {"evidence_text": "x" * 201},
        {"subject_process": ""},
        {"target_process": None},
        {"extra": "no"},
    ],
)
def test_relation_proto_validation_rejects_invalid_fields(changes):
    args = {"relations": [RELATION | changes]}
    with pytest.raises(ModelFailed):
        LangchainExtractionModel(_StubChat(_message(args)), "relations").complete("x")


def test_missing_relation_fields_and_too_many_relations_are_rejected():
    for relations in [[{"direction": "increases"}], [RELATION] * 9]:
        with pytest.raises(ModelFailed):
            LangchainExtractionModel(
                _StubChat(_message({"relations": relations})), "relations"
            ).complete("x")


def test_real_langchain_client_sends_forced_tool_and_parses_arguments():
    import httpx
    from langchain_openai import ChatOpenAI

    def respond(request):
        body = json.loads(request.content)
        assert body["tool_choice"] == {
            "type": "function",
            "function": {"name": "submit_extraction"},
        }
        assert body["parallel_tool_calls"] is False
        assert body["tools"][0]["function"]["parameters"]["required"] == ["what"]
        return httpx.Response(
            200,
            json={
                "id": "chat-test",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-4.1-mini",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "submit_extraction",
                                        "arguments": '{"what": ["fresh claim"]}',
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        chat = ChatOpenAI(model="gpt-4.1-mini", api_key="test-only", http_client=http)
        assert json.loads(
            LangchainExtractionModel(chat, "what").complete("Extract")
        ) == {"what": ["fresh claim"]}
