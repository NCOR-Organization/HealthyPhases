"""Tool enforcement, contract validation, and provider failures."""

import json

import pytest
from langchain_core.messages import AIMessage

from phases_v2.extraction.adapters.secondary.LangchainExtractionModel import (
    LangchainExtractionModel,
    NotAToolCallMessage,
    is_transient,
)
from phases_v2.extraction.interfaces import InvalidAnswer, ModelFailed
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
            {"results": ["x"] * 31},
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


class _StatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class APIConnectionError(Exception):
    """Stands in for the provider SDKs' same-named connection error."""


@pytest.mark.parametrize(
    "failure",
    [
        APIConnectionError("Connection error."),
        ConnectionResetError("reset"),
        TimeoutError("timed out"),
        _StatusError(429),
        _StatusError(500),
        _StatusError(503),
        _StatusError(529),
        _StatusError(408),
    ],
)
def test_connection_timeout_rate_limit_and_server_errors_are_transient(failure):
    chat = _StubChat(failure)
    with pytest.raises(ModelFailed) as caught:
        LangchainExtractionModel(chat).complete("x")
    assert caught.value.transient is True
    assert is_transient(failure)


@pytest.mark.parametrize(
    "failure",
    [_StatusError(400), _StatusError(401), _StatusError(404), RuntimeError("boom")],
)
def test_client_errors_and_unknown_errors_are_not_transient(failure):
    with pytest.raises(ModelFailed) as caught:
        LangchainExtractionModel(_StubChat(failure)).complete("x")
    assert caught.value.transient is False


def test_an_answer_under_the_legacy_key_is_accepted_as_the_current_one():
    chat = _StubChat(_message({"logical_sentences": ["If a, then b."]}))

    result = LangchainExtractionModel(chat, "conditional_statement").complete("x")

    assert json.loads(result) == {"conditional_statement": ["If a, then b."]}


def test_the_legacy_key_is_not_accepted_for_other_outputs():
    with pytest.raises(ModelFailed):
        LangchainExtractionModel(
            _StubChat(_message({"logical_sentences": ["x"]})), "what"
        ).complete("x")


def test_unusable_tool_output_is_never_transient():
    with pytest.raises(ModelFailed) as caught:
        LangchainExtractionModel(_StubChat(_message({"wrong": []}))).complete("x")
    assert caught.value.transient is False


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
        {"evidence_text": "x" * 501},
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
    for relations in [[{"direction": "increases"}], [RELATION] * 31]:
        with pytest.raises(ModelFailed):
            LangchainExtractionModel(
                _StubChat(_message({"relations": relations})), "relations"
            ).complete("x")


# -- what we accept, beyond what we ask for ---------------------------------


def _relations(**changes):
    return LangchainExtractionModel(
        _StubChat(_message({"relations": [RELATION | changes]})), "relations"
    )


@pytest.mark.parametrize("length", [200, 201, 500])
def test_evidence_up_to_500_characters_is_accepted(length):
    result = _relations(evidence_text="x" * length).complete("x")
    assert len(json.loads(result)["relations"][0]["evidence_text"]) == length


def test_30_relations_and_30_statements_are_accepted():
    relations = {"relations": [RELATION] * 30}
    statements = {"conditional_statement": ["If a, then b."] * 30}
    for output_key, args in (
        ("relations", relations),
        ("conditional_statement", statements),
    ):
        model = LangchainExtractionModel(_StubChat(_message(args)), output_key)
        assert json.loads(model.complete("x")) == args


@pytest.mark.parametrize("output_key", ["what", "causes", "how", "when", "where"])
def test_every_listed_output_accepts_30_items_and_rejects_31(output_key):
    accepted = {output_key: ["a claim"] * 30}
    model = LangchainExtractionModel(_StubChat(_message(accepted)), output_key)
    assert json.loads(model.complete("x")) == accepted
    with pytest.raises(InvalidAnswer, match=f"{output_key}: 31 items exceed 30"):
        LangchainExtractionModel(
            _StubChat(_message({output_key: ["a claim"] * 31})), output_key
        ).complete("x")


@pytest.mark.parametrize(
    ("output_key", "args", "error"),
    [
        (
            "relations",
            {
                "relations": [
                    RELATION,
                    RELATION,
                    RELATION | {"evidence_text": "x" * 612},
                ]
            },
            "invalid RelationsOutput: relations[2].evidence_text: "
            "length 612 exceeds 500",
        ),
        (
            "relations",
            {"relations": [RELATION | {"evidence_text": "x" * 501}]},
            "invalid RelationsOutput: relations[0].evidence_text: "
            "length 501 exceeds 500",
        ),
        (
            "relations",
            {"relations": [RELATION] * 31},
            "invalid RelationsOutput: relations: 31 items exceed 30",
        ),
        (
            "relations",
            {"relations": [RELATION | {"direction": "alters"}]},
            "invalid RelationsOutput: relations[0].direction: 'alters' is not one "
            "of increases, decreases, no-effect",
        ),
        (
            "relations",
            {"relations": [RELATION | {"target_process": ""}]},
            "invalid RelationsOutput: relations[0].target_process: is empty",
        ),
        (
            "relations",
            {"relations": [RELATION | {"evidence_text": ""}]},
            "invalid RelationsOutput: relations[0].evidence_text: is empty",
        ),
        (
            "relations",
            {"relations": [RELATION | {"confidence": "high"}]},
            "invalid RelationsOutput: relations[0]: unexpected field(s) confidence",
        ),
        (
            "relations",
            {"relations": [{"direction": "increases"}]},
            "invalid RelationsOutput: relations[0]: missing field(s) "
            "subject_process, subject_participant, target_process, evidence_text",
        ),
        (
            "conditional_statement",
            {"conditional_statement": ["If a, then b."] * 31},
            "invalid ConditionalStatementOutput: conditional_statement: "
            "31 items exceed 30",
        ),
        (
            "conditional_statement",
            {"conditional_statement": ["If a, then b.", ""]},
            "invalid ConditionalStatementOutput: conditional_statement[1]: is empty",
        ),
        (
            "what",
            {"what": [], "extra": "no"},
            "invalid WhatOutput: arguments: unexpected field(s) extra",
        ),
        (
            "what",
            {"what": "a single string"},
            "invalid WhatOutput: what: must be a list",
        ),
        (
            "what",
            {"what": [42]},
            "invalid WhatOutput: what[0]: must be a string",
        ),
    ],
)
def test_a_rejected_answer_names_the_field_and_the_rule(output_key, args, error):
    message = _message(args)
    with pytest.raises(InvalidAnswer) as caught:
        LangchainExtractionModel(_StubChat(message), output_key).complete("x")
    assert str(caught.value) == error
    assert caught.value.transient is False
    assert json.loads(caught.value.raw_response) == json.loads(
        message.model_dump_json()
    )


def test_many_rule_failures_are_summarised():
    args = {"relations": [RELATION | {"direction": "alters"}] * 5}
    with pytest.raises(InvalidAnswer) as caught:
        LangchainExtractionModel(_StubChat(_message(args)), "relations").complete("x")
    assert str(caught.value).endswith("; and 2 more")
    assert str(caught.value).count("'alters' is not one of") == 3


def test_a_stored_answer_is_reread_exactly_as_a_live_call_reads_it():
    args = {"relations": [RELATION | {"evidence_text": "x" * 230}]}
    stored = _message(args).model_dump_json()

    live = LangchainExtractionModel(_StubChat(_message(args)), "relations")

    assert LangchainExtractionModel.reread(stored, "relations") == live.complete("x")


def test_a_stored_answer_that_is_still_invalid_says_why():
    stored = _message({"relations": [RELATION | {"direction": "modulates"}]})
    with pytest.raises(InvalidAnswer, match=r"relations\[0\]\.direction: 'modulates'"):
        LangchainExtractionModel.reread(stored.model_dump_json(), "relations")


def test_a_stored_answer_that_is_not_a_message_cannot_be_reread():
    with pytest.raises(NotAToolCallMessage):
        LangchainExtractionModel.reread('{"relations": []', "relations")


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
