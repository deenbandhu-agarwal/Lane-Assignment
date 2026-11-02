"""Tag inverted index (implements ports.PostingSource): 'key=value' -> series ids. In memory,
rebuilt from series.log at startup. Keeps a posting list per metric: the universe for `!=`."""

from __future__ import annotations

import threading

from tsdb.model import SeriesId, SeriesKey


class InvertedIndex:
    def __init__(self) -> None:
        self._postings: dict[tuple[str, str], set[SeriesId]] = {}
        self._by_metric: dict[str, set[SeriesId]] = {}
        self._all: set[SeriesId] = set()
        self._lock = threading.Lock()     # writers add; readers take frozen copies

    def add(self, series_id: SeriesId, key: SeriesKey) -> None:
        with self._lock:
            for tag in key.tags:
                self._postings.setdefault(tag, set()).add(series_id)
            self._by_metric.setdefault(key.metric, set()).add(series_id)
            self._all.add(series_id)

    def postings(self, tag_key: str, tag_value: str) -> frozenset[SeriesId]:
        """A frozen copy: a query never sees a set change under it."""
        with self._lock:
            return frozenset(self._postings.get((tag_key, tag_value), ()))

    def metric_universe(self, metric: str | None) -> frozenset[SeriesId]:
        """None = every series of every metric."""
        with self._lock:
            return frozenset(self._all if metric is None else self._by_metric.get(metric, ()))

    def size_of(self, tag_key: str, tag_value: str) -> int:
        with self._lock:
            return len(self._postings.get((tag_key, tag_value), ()))
