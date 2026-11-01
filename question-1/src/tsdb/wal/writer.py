"""Group-commit writer for ONE WAL file (one background thread).

Loop:
    1. take everything waiting in the queue
       --- swap_lock.shared() (design-qa #45, D2) ---
    2. give each entry the next seq (taken here, at append time, so seq rises inside this file)
    3. append all frames to the segment            -> faults.hit(WAL_APPEND)
    4. before_fsync() = catalog.sync() (series.log FIRST, design-qa #46), then ONE fsync for the group
    5. apply the entries to the memtable (callback); seq.mark_applied(block)
       --- release shared ---
    6. seq.wait_until_visible(last seq of the group)  (D1: no reply before every older seq is visible)
    7. complete every waiting ticket -> the HTTP handlers reply 200
If fsync or apply fails: every ticket in the group (and every later one) gets the error and the
HTTP layer answers 500 and stops the process; recovery replays the WAL. A failed fsync is never
retried: the kernel may have dropped the dirty pages, so a second fsync could "succeed" on lost data.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from tsdb.engine.seq import SequenceCounter
from tsdb.engine.swap_lock import SwapLock
from tsdb.faults import CrashPoint
from tsdb.model import Point, SeriesId, Timestamp, Tombstone
from tsdb.ports import FaultInjector
from tsdb.wal.record import encode_delete, encode_put, frame
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
BeforeFsyncFn = Callable[[], None]


class WalWriter:
    def __init__(self, index: int, segment: WalSegment, seq: SequenceCounter, swap_lock: SwapLock,
                 apply: ApplyFn, before_fsync: BeforeFsyncFn, faults: FaultInjector) -> None:
        self._index = index
        self._swap_lock = swap_lock
        self._segment = segment
        self._seq = seq
        self._apply = apply
        self._before_fsync = before_fsync
        self._faults = faults
        self._queue: queue.SimpleQueue[Ticket] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._failed: BaseException | None = None   # set once; never cleared (no fsync retry)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"wal-writer-{self._index}", daemon=True)
        self._thread.start()

    def submit(self, ticket: Ticket) -> None:
        """Returns at once; the caller waits on ticket.done and then checks ticket.error."""
        self._queue.put(ticket)

    def switch_segment(self, new_segment: WalSegment) -> WalSegment:
        """Called by WalSet.rotate_all() under swap_lock.exclusive(). Returns the old segment."""
        old, self._segment = self._segment, new_segment
        return old

    def set_apply(self, apply: ApplyFn) -> None:
        """Point at the new active memtable after a swap (also under swap_lock.exclusive())."""
        self._apply = apply

    def stop(self) -> None:
        if self._thread is not None:
            self._queue.put(_STOP)
            self._thread.join()
            self._thread = None
        self._segment.close()

    def _run(self) -> None:
        while True:
            first = self._queue.get()                     # wait for work
            if first is _STOP:
                return
            group = [first]
            while True:                                   # everything else already waiting joins the group
                try:
                    more = self._queue.get_nowait()
                except queue.Empty:
                    break
                if more is _STOP:
                    self._queue.put(_STOP)
                    break
                group.append(more)
            if self._failed is None:
                try:
                    self._commit(group)
                    continue
                except Exception as e:            # FatalStorageError, or apply failed half way
                    self._failed = e
            for t in group:
                t.error = self._failed
                t.done.set()

    def _commit(self, group: list[Ticket]) -> None:
        pending = [e for t in group for e in t.entries]
        with self._swap_lock.shared():
            first_seq = self._seq.next_block(len(pending))
            entries = [_with_seq(e, first_seq + i) for i, e in enumerate(pending)]
            self._segment.append(b"".join(
                frame(encode_put(e) if isinstance(e, Point) else encode_delete(e)) for e in entries))
            self._faults.hit(CrashPoint.WAL_APPEND)
            self._before_fsync()
            self._segment.sync()
            self._apply(entries)
            self._seq.mark_applied(first_seq, len(entries))
        self._seq.wait_until_visible(first_seq + len(entries) - 1)
        for t in group:
            t.done.set()


_STOP = object()


def _with_seq(entry: PendingPut | PendingDelete, seq: int) -> Point | Tombstone:
    if isinstance(entry, PendingPut):
        return Point(entry.series_id, entry.timestamp, seq, entry.value)
    return Tombstone(seq, entry.series_ids, entry.from_ts, entry.to_ts)
