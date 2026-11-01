"""Merge-on-read for ONE series across all sources (memtables + SSTables of every level).

    sources  : iterators of Point, each in (timestamp asc, seq desc) order, already limited to the
               snapshot seq and [from, to]
    merge    : k-way merge (heap) by timestamp; for equal timestamps the highest seq wins
    hide     : drop the winner if any tombstone covers (series, timestamp) with tombstone.seq > point.seq
Output: one point per timestamp, ascending. Streaming (constant memory per series).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from tsdb.model import Point, Tombstone


def merge_series(sources: Iterable[Iterator[Point]], tombstones: list[Tombstone]) -> Iterator[Point]:
    raise NotImplementedError
