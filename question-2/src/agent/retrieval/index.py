"""Hybrid retriever: BM25 + flat cosine, fused with RRF. Mode is a parameter so the
experiment (bm25 | vector | hybrid) runs the exact same code.

"Not relevant" is decided on the raw signals, not on RRF scores (which are rank-based
and always look fine): a chunk survives only if its BM25 score or its cosine clears
a floor. If nothing survives, search returns no results and the agent says so.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np

from agent.retrieval.bm25 import BM25
from agent.retrieval.chunker import Chunk
from agent.retrieval.embedders import Embedder
from agent.retrieval.rrf import rrf
from agent.retrieval.vectors import VectorIndex


class Mode(StrEnum):
    BM25 = "bm25"
    VECTOR = "vector"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float  # RRF score in hybrid mode, else the raw BM25 score / cosine
    bm25: float
    cosine: float


def corpus_key(embedder_name: str, chunks: list[Chunk]) -> str:
    h = hashlib.sha256(embedder_name.encode())
    for c in chunks:
        h.update(c.id.encode() + b"\0" + c.text.encode() + b"\0")
    return h.hexdigest()[:16]


class Retriever:
    def __init__(
        self,
        chunks: list[Chunk],
        embedder: Embedder,
        *,
        mode: Mode = Mode.HYBRID,
        bm25_min: float = 3.0,
        candidates: int = 20,  # per-ranker depth fed into RRF
        cache_dir: Path | None = None,
    ) -> None:
        if not chunks:
            raise ValueError("empty corpus")
        self.chunks = chunks
        self.embedder = embedder
        self.mode = Mode(mode)
        self.bm25_min = bm25_min
        self.candidates = candidates
        self._bm25 = BM25([c.text for c in chunks])
        self._vec = VectorIndex(self._embed_corpus(cache_dir))

    def _embed_corpus(self, cache_dir: Path | None) -> np.ndarray:
        texts = [c.text for c in self.chunks]
        if cache_dir is None:
            return self.embedder.embed_documents(texts)
        path = Path(cache_dir) / f"emb-{corpus_key(self.embedder.name, self.chunks)}.npy"
        if path.exists():
            return np.load(path)
        vecs = self.embedder.embed_documents(texts)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, vecs)
        return vecs

    def search(self, query: str, k: int = 5) -> list[Hit]:
        bm = self._bm25.scores(query)
        cos = self._vec.similarities(self.embedder.embed_query(query))
        floor = self.embedder.min_similarity

        def relevant(i: int) -> bool:
            if self.mode is Mode.BM25:
                return bm[i] >= self.bm25_min
            if self.mode is Mode.VECTOR:
                return cos[i] >= floor
            return bm[i] >= self.bm25_min or cos[i] >= floor

        bm_rank = [i for i, _ in self._bm25.search(query, self.candidates)]
        vec_rank = [i for i, _ in self._vec.search(self.embedder.embed_query(query), self.candidates)]
        if self.mode is Mode.BM25:
            ranked = [(i, bm[i]) for i in bm_rank]
        elif self.mode is Mode.VECTOR:
            ranked = [(i, float(cos[i])) for i in vec_rank]
        else:
            ranked = rrf([bm_rank, vec_rank])

        hits = [
            Hit(self.chunks[i], float(s), float(bm[i]), float(cos[i]))
            for i, s in ranked
            if relevant(i)
        ]
        return hits[:k]
