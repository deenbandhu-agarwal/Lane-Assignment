"""Embedder port + two adapters.

FastEmbedEmbedder: real local model (bge-small, ONNX on CPU). No network after the
one-time model download.
FakeEmbedder: deterministic hashed bag-of-words for offline tests. It behaves like a
keyword matcher, so tests using it prove plumbing, not semantic quality.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol

import numpy as np

from agent.retrieval.bm25 import tokenize
from agent.retrieval.vectors import normalize


class Embedder(Protocol):
    name: str
    min_similarity: float  # below this cosine a hit counts as "not relevant"

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


class FakeEmbedder:
    name = "fake-hash-4096"
    min_similarity = 0.08  # bag-of-words cosine: one shared rare word in a ~50-word chunk is ~0.1

    def __init__(self, dim: int = 4096) -> None:
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in tokenize(text):
            h = int.from_bytes(hashlib.md5(tok.encode()).digest()[:4], "little")
            v[h % self.dim] += 1.0 if (h >> 31) & 1 else -1.0
        return v

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return normalize(np.stack([self._vec(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return normalize(self._vec(text))


class FastEmbedEmbedder:
    # bge-small puts unrelated text at ~0.54-0.58 cosine on this corpus (calibration run,
    # unanswerable questions); relevant sections mostly score above 0.6.
    min_similarity = 0.60

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", cache_dir: str | None = None):
        from fastembed import TextEmbedding  # lazy: tests never load the model

        self.name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return normalize(np.stack(list(self._model.passage_embed(list(texts)))))

    def embed_query(self, text: str) -> np.ndarray:
        return normalize(next(iter(self._model.query_embed(text))))
