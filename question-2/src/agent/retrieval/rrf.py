"""Reciprocal Rank Fusion (Cormack, Clarke & Buettcher, 2009).

score(d) = sum over rankings r of 1 / (k + rank_r(d)),  rank starting at 1.
Uses only positions, so BM25 scores (unbounded) and cosines (-1..1) never need
to be put on the same scale. k = 60 damps the advantage of the very top rank.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from typing import TypeVar

K = TypeVar("K", bound=Hashable)


def rrf(rankings: Sequence[Sequence[K]], k: int = 60) -> list[tuple[K, float]]:
    scores: dict[K, float] = {}
    first_seen: dict[K, int] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(item, len(first_seen))
    return sorted(scores.items(), key=lambda kv: (-kv[1], first_seen[kv[0]]))
