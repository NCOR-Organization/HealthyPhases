"""Exercise the real LangChain tokenizer/batching path without API calls."""

from types import SimpleNamespace

import pytest

from phases_v2.projection.adapters.secondary.OpenAIEmbedder import OpenAIEmbedder


def test_large_corpus_and_long_inputs_stay_below_request_token_limit(monkeypatch):
    import openai.resources.embeddings
    import tiktoken

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        tiktoken,
        "encoding_for_model",
        lambda _: SimpleNamespace(encode_ordinary=lambda text: [1] * int(text)),
    )
    requests = []

    def create(self, *, input, **kwargs):
        assert self._client.api_key == "configured-test-key"
        requests.append(input)
        assert sum(map(len, input)) < 300_000
        assert all(len(tokens) <= 8191 for tokens in input)
        return {"data": [{"embedding": [1.0, 0.0]} for _ in input]}

    monkeypatch.setattr(openai.resources.embeddings.Embeddings, "create", create)
    texts = ["8191"] * 70 + ["20000"]
    vectors = OpenAIEmbedder(dimension=2, api_key="configured-test-key").embed(texts)
    assert len(vectors) == len(texts)
    assert vectors == [[1.0, 0.0]] * len(texts)
    assert len(requests) == 3
    assert sum(sum(map(len, request)) for request in requests) == 70 * 8191 + 20000


def test_empty_input_never_builds_a_client():
    embedder = OpenAIEmbedder()
    assert embedder.embed([]) == []
    assert embedder._client is None


def test_missing_module_key_does_not_silently_use_process_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-process-key")
    with pytest.raises(ValueError, match="phases_v2.config.openai_api_key"):
        OpenAIEmbedder().embed(["solitude"])
