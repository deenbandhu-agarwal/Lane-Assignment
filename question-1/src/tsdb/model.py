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


@dataclass(frozen=True, slots=True)
class ManifestState:
    """Content of the MANIFEST: which files are live. Value type shared by ManifestPort users."""

    version: int                          # +1 on every commit
    next_file_no: int                     # next SSTable file number
    last_flushed_seq: int                 # every seq <= this is inside some SSTable
    wal_count: int                        # N; must not change without migration (routing)
    wal_segment: int                      # current segment number, shared by all N WALs
    levels: tuple[tuple[str, ...], ...] = ()   # levels[n] = file names (L0 newest first)


class Aggregation(str, Enum):
    AVG = "avg"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
