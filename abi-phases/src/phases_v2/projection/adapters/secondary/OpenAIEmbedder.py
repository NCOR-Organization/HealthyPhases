"""Embeddings from the same model ``phases`` uses.

Keeping the model and dimension identical to v1 means the two corpora stay
comparable if they are ever searched together.
"""

from __future__ import annotations

from typing import Any

MODEL = "text-embedding-3-large"
DIMENSION = 3072
# LangChain splits long inputs before batching: at most 32 * 8191 = 262112
# tokens per API request, below OpenAI's 300000-token aggregate limit.
TOKEN_CHUNK_SIZE = 8191
REQUEST_CHUNKS = 32


class OpenAIEmbedder:
    def __init__(self, model: str = MODEL, dimension: int = DIMENSION):
        self._model = model
        self._dimension = dimension
        self._client: Any = None

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[Any]:
        if not texts:
            return []
        if self._client is None:
            from langchain_openai import OpenAIEmbeddings

            self._client = OpenAIEmbeddings(
                model=self._model,
                dimensions=self._dimension,
                embedding_ctx_length=TOKEN_CHUNK_SIZE,
                chunk_size=REQUEST_CHUNKS,
            )
        return self._client.embed_documents(texts)
