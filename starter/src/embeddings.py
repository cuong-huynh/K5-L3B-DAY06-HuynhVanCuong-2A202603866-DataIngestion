"""Local multilingual embeddings via Sentence Transformers (no API key, no cost)."""
from typing import Protocol

from sentence_transformers import SentenceTransformer


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class E5Embedder:
    """multilingual-e5 models expect 'passage: ' / 'query: ' prefixes; vectors are L2-normalized."""

    def __init__(self, model_name: str = "intfloat/multilingual-e5-small",
                 batch_size: int = 32) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name, device="cpu")
        self.dimensions = self.model.get_embedding_dimension()
        self.max_seq_length = self.model.max_seq_length

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, batch_size=self.batch_size,
                                    normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([f"passage: {t}" for t in texts])

    def embed_query(self, question: str) -> list[float]:
        return self._encode([f"query: {question}"])[0]

    def count_truncated(self, texts: list[str]) -> int:
        """Number of passages longer than the model's token limit (they get truncated)."""
        tokenizer = self.model.tokenizer
        return sum(len(tokenizer(f"passage: {t}")["input_ids"]) > self.max_seq_length for t in texts)
