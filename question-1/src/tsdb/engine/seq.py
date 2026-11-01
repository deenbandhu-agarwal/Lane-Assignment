"""The shard's sequence counter: a logical clock. Every PUT and DELETE gets the next number.

Thread-safe (explicit lock: correct on free-threaded Python too). `observe` implements the Lamport
rule (counter = max(counter, seen)) used by recovery and, later, by moving series between shards.

Visible seq (design-qa #45, D1): with N WALs, groups can reach the memtable out of seq order
(WAL B applies seq 11 while WAL A is still fsyncing seq 10). `visible` = highest V such that EVERY
seq <= V is applied. Queries snapshot at `visible`, never at `last`; a WAL writer replies 200 only
after `wait_until_visible(its last seq)`, so a client always reads its own acknowledged write.
With N = 1 (default) groups apply in order and `visible` simply follows the last applied seq.
"""

from __future__ import annotations

import threading

from tsdb.model import Seq


class SequenceCounter:
    def __init__(self, last: Seq = 0) -> None:
        self._last = last
        self._visible = last
        self._applied_ahead: dict[Seq, int] = {}     # first -> n, applied but above `visible`
        self._lock = threading.Lock()
        self._visible_changed = threading.Condition(self._lock)

    def next_block(self, n: int) -> Seq:
        """Reserve n consecutive numbers; return the first. They are IN FLIGHT until mark_applied."""
        with self._lock:
            first = self._last + 1
            self._last += n
            return first

    def mark_applied(self, first: Seq, n: int) -> None:
        """The block [first, first + n) is in the memtable; may raise `visible`."""
        with self._lock:
            self._applied_ahead[first] = n
            while (size := self._applied_ahead.pop(self._visible + 1, None)) is not None:
                self._visible += size
            self._visible_changed.notify_all()

    @property
    def visible(self) -> Seq:
        """Every seq <= this is applied: the snapshot seq for a new query."""
        with self._lock:
            return self._visible

    def wait_until_visible(self, seq: Seq) -> None:
        with self._lock:
            self._visible_changed.wait_for(lambda: self._visible >= seq)

    def observe(self, seen: Seq) -> None:
        """Recovery only (before any writer runs): nothing is in flight, so visible moves too."""
        with self._lock:
            if seen > self._last:
                self._last = self._visible = seen

    @property
    def last(self) -> Seq:
        """Highest number handed out (MANIFEST / recovery). NOT a snapshot seq: use `visible`."""
        with self._lock:
            return self._last
