"""Series catalog (implements ports.SeriesResolver): series key <-> id, persisted in series.log.

Lookup happens in the write path BEFORE the WAL (WAL records store only the id).
A plain dict is fine here: the brief's "no Map-as-sorted-structure" rule is about the memtable.
New series are pushed to the index through a callback, so the catalog does not depend on the index class.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from tsdb.model import SeriesId, SeriesKey
from tsdb.ports import FileOps

OnNewSeries = Callable[[SeriesId, SeriesKey], None]


class SeriesCatalog:
    def __init__(self, series_log: Path, files: FileOps, on_new_series: OnNewSeries) -> None:
        self._series_log = series_log
        self._files = files
        self._on_new_series = on_new_series
        self._key_to_id: dict[str, SeriesId] = {}
        self._id_to_key: list[SeriesKey | None] = [None]   # ids start at 1
        self._create_lock = threading.Lock()                # only for creating new series

    def load(self) -> None:
        """Replay series.log (framed records; drop a cut tail) and call on_new_series for each."""
        raise NotImplementedError

    def get_or_create(self, key: SeriesKey) -> tuple[SeriesId, bool]:
        """Fast path: dict lookup, no lock. Slow path: lock, re-check, append to series.log,
        notify the index. Returns (id, created). Fsynced together with the WAL batch (sync())."""
        raise NotImplementedError

    def key_of(self, series_id: SeriesId) -> SeriesKey:
        raise NotImplementedError

    def sync(self) -> None:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError
