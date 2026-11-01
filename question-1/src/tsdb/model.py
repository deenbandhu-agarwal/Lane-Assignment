"""Core value types shared by every layer. Plain, immutable, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

SeriesId = int    # u32, assigned by the series catalog, local to a shard
Timestamp = int   # Unix epoch milliseconds (i64)
Seq = int         # global write order inside a shard (u64); bigger = newer


@dataclass(frozen=True, slots=True)
class SeriesKey:
    """metric + full tag set. Identity of a series. Tag order never matters."""

    metric: str
    tags: tuple[tuple[str, str], ...]   # sorted by tag key

    @staticmethod
    def of(metric: str, tags: dict[str, str]) -> "SeriesKey":
        """Normalise: sort tags by key."""
        raise NotImplementedError

    def canonical(self) -> str:
        """'temperature{city=Delhi,sensor=roof}' — stored in series.log, hashed for WAL routing."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Point:
    """One stored version of one sample."""

    series_id: SeriesId
    timestamp: Timestamp
    seq: Seq
    value: float


@dataclass(frozen=True, slots=True)
class Tombstone:
    """Range delete: hides points of these series in [from_ts, to_ts] whose seq < self.seq."""

    seq: Seq
    series_ids: tuple[SeriesId, ...]
    from_ts: Timestamp
    to_ts: Timestamp

    def hides(self, series_id: SeriesId, timestamp: Timestamp, seq: Seq) -> bool:
        raise NotImplementedError

    def clip(self, window: "TimeWindow") -> "Tombstone | None":
        """The piece of this tombstone inside `window` (None if no overlap). Flush cuts every
        tombstone at window edges so each window's files carry their own part of the delete."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True, order=True)
class TimeWindow:
    """[start, start + size) aligned to the epoch. Every SSTable belongs to exactly one window.
    Window sizes are steps (e.g. 1 h -> 6 h -> 1 day), each a multiple of the previous, so windows
    nest exactly: every small window lies inside exactly one window of each bigger step."""

    size_ms: int
    start_ms: Timestamp

    @staticmethod
    def containing(timestamp: Timestamp, size_ms: int) -> "TimeWindow":
        """start = timestamp - (timestamp mod size)."""
        return TimeWindow(size_ms, timestamp - timestamp % size_ms)

    @property
    def end_ms(self) -> Timestamp:
        """Last millisecond inside the window (inclusive)."""
        return self.start_ms + self.size_ms - 1

    def contains(self, timestamp: Timestamp) -> bool:
        return self.start_ms <= timestamp <= self.end_ms

    def overlaps(self, from_ts: Timestamp, to_ts: Timestamp) -> bool:
        """[from_ts, to_ts] is inclusive on both ends, like the query range."""
        return from_ts <= self.end_ms and to_ts >= self.start_ms

    def parent(self, bigger_size_ms: int) -> "TimeWindow":
        if bigger_size_ms <= self.size_ms or bigger_size_ms % self.size_ms:
            raise ValueError(f"{bigger_size_ms} ms is not a bigger multiple of {self.size_ms} ms")
        return TimeWindow.containing(self.start_ms, bigger_size_ms)

    def children(self, smaller_size_ms: int) -> list["TimeWindow"]:
        if smaller_size_ms >= self.size_ms or self.size_ms % smaller_size_ms:
            raise ValueError(f"{smaller_size_ms} ms does not divide {self.size_ms} ms")
        return [TimeWindow(smaller_size_ms, start)
                for start in range(self.start_ms, self.start_ms + self.size_ms, smaller_size_ms)]

    def is_closed(self, newest_data_ts: Timestamp, grace_ms: int) -> bool:
        """Closed when the newest DATA timestamp written is past end + grace (grace = one smallest
        window). Uses data time, not wall clock: deterministic tests, past timestamps work."""
        raise NotImplementedError

    def label(self) -> str:
        """Directory name: '<size_ms>/<start_ms>' (dump tool prints it human-readable)."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ManifestState:
    """Content of the MANIFEST: which files are live. Value type shared by ManifestPort users."""

    version: int                          # +1 on every commit
    next_file_no: int                     # next SSTable file number
    last_flushed_seq: int                 # every seq <= this is inside some SSTable
    wal_count: int                        # N; must not change without migration (routing)
    wal_segment: int                      # current segment number, shared by all N WALs
    newest_data_ts: Timestamp = 0         # newest timestamp ever flushed (drives window closing)
    windows: tuple[tuple[TimeWindow, tuple[str, ...]], ...] = ()   # window -> live file names


class Aggregation(str, Enum):
    AVG = "avg"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
