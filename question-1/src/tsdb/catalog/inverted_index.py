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
        raise NotImplementedError

    def postings(self, tag_key: str, tag_value: str) -> frozenset[SeriesId]:
        raise NotImplementedError

    def metric_universe(self, metric: str | None) -> frozenset[SeriesId]:
        raise NotImplementedError

    def size_of(self, tag_key: str, tag_value: str) -> int:
        raise NotImplementedError
