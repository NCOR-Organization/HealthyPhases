import numpy as np
from langchain_openai import OpenAIEmbeddings


# We need to compute embeddings for the markdown chunks.
# Split the markdown into overlapping chunks
def split_to_overlapping_chunks(text: str, chunk_size: int = 512, overlap: int = 128) -> list[str]:
    tokens = text.split()
    chunks = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        chunk = " ".join(tokens[start:end])
        chunks.append(chunk)
        if end >= len(tokens):
            break
        start += chunk_size - overlap
    return chunks


# We need to compute the embeddings for the chunks.
def compute_embeddings(chunks: list[str]) -> list[np.ndarray]:
    embeddings = OpenAIEmbeddings(model="text-embedding-3-large", dimensions=3072)
    return [np.array(embedding) for embedding in embeddings.embed_documents(chunks)]

def embed_text(text: str, chunk_size: int = 512, overlap: int = 128) -> tuple[list[str], list[np.ndarray]]:
        chunks: list[str] = split_to_overlapping_chunks(text, chunk_size=chunk_size, overlap=overlap)
        embeddings: list[np.ndarray] = compute_embeddings(chunks)            
        return chunks, embeddings