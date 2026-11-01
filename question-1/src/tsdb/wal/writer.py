"""Group-commit writer for ONE WAL file (one background thread).

Loop:
    1. take everything waiting in the queue
       --- swap_lock.shared() (design-qa #45, D2) ---
    2. give each entry the next seq (taken here, at append time, so seq rises inside this file)
    3. append all frames to the segment            -> faults.hit(WAL_APPEND)
    4. ONE fsync for the whole group (+ series.log via before_ack, if new series)
    5. apply the entries to the memtable (callback); seq.mark_applied(block)
       --- release shared ---
    6. seq.wait_until_visible(last seq of the group)  (D1: no reply before every older seq is visible)
    7. complete every waiting ticket -> the HTTP handlers reply 200
If fsync or apply fails: FatalStorageError -> the process stops; recovery replays the WAL.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from tsdb.engine.seq import SequenceCounter
from tsdb.engine.swap_lock import SwapLock
from tsdb.model import Point, SeriesId, Timestamp, Tombstone
from tsdb.ports import FaultInjector
from tsdb.wal.segment import WalSegment


@dataclass(slots=True)
class PendingPut:
    series_id: SeriesId
    timestamp: Timestamp
    value: float


@dataclass(slots=True)
class PendingDelete:
    series_ids: tuple[SeriesId, ...]
    from_ts: Timestamp
    to_ts: Timestamp


@dataclass(slots=True)
class Ticket:
    """One request's part for this WAL. The request waits until every ticket is done."""

    entries: list[PendingPut | PendingDelete]
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


ApplyFn = Callable[[list[Point | Tombstone]], None]
BeforeAckFn = Callable[[], None]


class WalWriter:
    def __init__(self, index: int, segment: WalSegment, seq: SequenceCounter, swap_lock: SwapLock,
                 apply: ApplyFn, before_ack: BeforeAckFn, faults: FaultInjector) -> None:
        self._index = index
        self._swap_lock = swap_lock
        self._segment = segment
        self._seq = seq
        self._apply = apply
        self._before_ack = before_ack
        self._faults = faults
        self._queue: queue.SimpleQueue[Ticket] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        raise NotImplementedError

    def submit(self, ticket: Ticket) -> None:
        raise NotImplementedError

    def switch_segment(self, new_segment: WalSegment) -> WalSegment:
        """Called by WalSet.rotate_all() under swap_lock.exclusive(). Returns the old segment."""
        raise NotImplementedError

    def set_apply(self, apply: ApplyFn) -> None:
        """Point at the new active memtable after a swap."""
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def _run(self) -> None:
        raise NotImplementedError
