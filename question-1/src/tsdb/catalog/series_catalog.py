"""Series catalog (implements ports.SeriesResolver): series key <-> id, persisted in series.log.

Lookup happens in the write path BEFORE the WAL (WAL records store only the id).
Record (inside the WAL frame: length | crc32 | payload):  series_id u32 | JSON [metric, [[k, v], ...]]
JSON, not the canonical text, so loading needs no un-escape parser.
Durability order (design-qa #46): series.log is fsynced BEFORE the WAL fsync of the same group, so
a durable WAL record never names an id that series.log does not know.
A plain dict is fine here: the brief's "no Map-as-sorted-structure" rule is about the memtable.
New series are pushed to the index through a callback, so the catalog does not depend on the index class.
"""

from __future__ import annotations

import json
import struct
import threading
from collections.abc import Callable
from pathlib import Path

from tsdb.model import SeriesId, SeriesKey
from tsdb.ports import FileOps
from tsdb.wal.record import frame, scan_frames

_ID = struct.Struct("<I")

OnNewSeries = Callable[[SeriesId, SeriesKey], None]


class SeriesCatalog:
    def __init__(self, series_log: Path, files: FileOps, on_new_series: OnNewSeries) -> None:
        self._series_log = series_log
        self._files = files
        self._on_new_series = on_new_series
        self._key_to_id: dict[SeriesKey, SeriesId] = {}
        self._id_to_key: list[SeriesKey | None] = [None]   # ids start at 1
        self._create_lock = threading.Lock()                # only for creating new series
        self._fd: int | None = None
        self._dirty = False

    def load(self) -> None:
        """Replay series.log (framed records; drop a cut tail) and call on_new_series for each."""
        data = self._files.read_all(self._series_log) if self._series_log.exists() else b""
        frames, valid_length, _ = scan_frames(data)
        if valid_length < len(data):
            self._files.truncate(self._series_log, valid_length)    # else new records hide behind garbage
        for _, payload in frames:
            (series_id,) = _ID.unpack_from(payload)
            metric, tags = json.loads(payload[_ID.size:])
            self._remember(series_id, SeriesKey(metric, tuple(tuple(t) for t in tags)))
        self._fd = self._files.open_append(self._series_log)

    def get_or_create(self, key: SeriesKey) -> tuple[SeriesId, bool]:
        """Fast path: dict lookup, no lock. Slow path: lock, re-check, append to series.log,
        notify the index. Returns (id, created). Made durable by sync(), which the WAL writer calls
        BEFORE its own fsync."""
        series_id = self._key_to_id.get(key)
        if series_id is not None:
            return series_id, False
        with self._create_lock:
            series_id = self._key_to_id.get(key)
            if series_id is not None:
                return series_id, False
            series_id = len(self._id_to_key)
            body = json.dumps([key.metric, [list(t) for t in key.tags]], ensure_ascii=False).encode()
            self._files.append(self._fd, frame(_ID.pack(series_id) + body))
            self._dirty = True
            self._remember(series_id, key)
            return series_id, True

    def key_of(self, series_id: SeriesId) -> SeriesKey:
        return self._id_to_key[series_id]

    def sync(self) -> None:
        with self._create_lock:
            if self._dirty:
                self._files.fsync(self._fd)
                self._dirty = False

    def __len__(self) -> int:
        return len(self._id_to_key) - 1

    def _remember(self, series_id: SeriesId, key: SeriesKey) -> None:
        """id -> key first, then key -> id: a reader who finds the id can always resolve it."""
        self._id_to_key.append(key)
        self._key_to_id[key] = series_id
        self._on_new_series(series_id, key)
