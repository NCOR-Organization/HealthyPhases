"""Exercise the real LangChain tokenizer/batching path without API calls."""

from types import SimpleNamespace

from phases_v2.projection.adapters.secondary.OpenAIEmbedder import OpenAIEmbedder


def test_large_corpus_and_long_inputs_stay_below_request_token_limit(monkeypatch):
    import openai.resources.embeddings
    import tiktoken

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(
        tiktoken,
        "encoding_for_model",
        lambda _: SimpleNamespace(encode_ordinary=lambda text: [1] * int(text)),
    )
    requests = []

    def create(self, *, input, **kwargs):
        requests.append(input)
        assert sum(map(len, input)) < 300_000
        assert all(len(tokens) <= 8191 for tokens in input)
        return {"data": [{"embedding": [1.0, 0.0]} for _ in input]}

    monkeypatch.setattr(openai.resources.embeddings.Embeddings, "create", create)
    texts = ["8191"] * 70 + ["20000"]
    vectors = OpenAIEmbedder(dimension=2).embed(texts)
    assert len(vectors) == len(texts)
    assert vectors == [[1.0, 0.0]] * len(texts)
    assert len(requests) == 3
    assert sum(sum(map(len, request)) for request in requests) == 70 * 8191 + 20000


def test_empty_input_never_builds_a_client():
    embedder = OpenAIEmbedder()
    assert embedder.embed([]) == []
    assert embedder._client is None
