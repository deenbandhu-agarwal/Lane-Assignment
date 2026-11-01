"""Flat (brute-force) cosine index: a matrix and one matrix-vector product. No ANN, no vector DB."""

from __future__ import annotations

import numpy as np


def normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


class VectorIndex:
    def __init__(self, vectors: np.ndarray) -> None:
        self._m = normalize(vectors)  # (n, dim), unit rows

    def __len__(self) -> int:
        return self._m.shape[0]

    def similarities(self, query_vec: np.ndarray) -> np.ndarray:
        return self._m @ normalize(query_vec)  # cosine, since rows and query are unit length

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        sims = self.similarities(query_vec)
        order = sorted(range(len(sims)), key=lambda i: (-float(sims[i]), i))[:k]
        return [(i, float(sims[i])) for i in order]
