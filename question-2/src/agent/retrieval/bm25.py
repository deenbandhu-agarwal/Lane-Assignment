"""Okapi BM25, from scratch.

score(q, d) = sum over query terms t of
    idf(t) * tf(t,d) * (k1 + 1) / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))
idf(t) = ln(1 + (N - n_t + 0.5) / (n_t + 0.5))      (Lucene's non-negative variant)

Rare terms (an error code) weigh a lot; common terms almost nothing; long
documents are not rewarded just for being long (b).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

_TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i if in is it its of on or "
    "our should so that the their them then there these this to was we what when where which "
    "who why will with you your".split()
)


def stem(t: str) -> str:
    """Tiny plural stripper: approvals -> approval, policies -> policy. Not a full stemmer."""
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


class BM25:
    def __init__(self, docs: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._tfs = [Counter(tokenize(d)) for d in docs]
        self._lens = [sum(tf.values()) for tf in self._tfs]
        self.n = len(docs)
        self._avgdl = (sum(self._lens) / self.n) if self.n else 0.0
        df: Counter[str] = Counter()
        for tf in self._tfs:
            df.update(tf.keys())
        self._idf = {t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        out = []
        for tf, dl in zip(self._tfs, self._lens):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * dl / self._avgdl) if self._avgdl else self.k1
            for t in terms:
                f = tf.get(t)
                if f:
                    s += self._idf[t] * f * (self.k1 + 1) / (f + norm)
            out.append(s)
        return out

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        """Top-k (doc index, score), score > 0 only, best first; ties broken by index."""
        ranked = sorted(
            ((i, s) for i, s in enumerate(self.scores(query)) if s > 0), key=lambda x: (-x[1], x[0])
        )
        return ranked[:k]
