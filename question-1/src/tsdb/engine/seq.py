"""The shard's sequence counter: a logical clock. Every PUT and DELETE gets the next number.

Thread-safe (explicit lock: correct on free-threaded Python too). `observe` implements the Lamport
rule (counter = max(counter, seen)) used by recovery and, later, by moving series between shards.

Two numbers:
    last     highest number handed out (a group may still be fsyncing it)
    visible  highest number applied to the memtable: the snapshot seq for a new query
There is ONE WAL writer thread, so groups are applied in seq order and `visible` is simply the end
of the last applied block. (With several WALs, blocks could be applied out of order and `visible`
would need to wait for every older block; that version was removed with multi-WAL, design-qa #54.)
"""

from __future__ import annotations

import threading

from tsdb.model import Seq


class SequenceCounter:
    def __init__(self, last: Seq = 0) -> None:
        self._last = last
        self._visible = last
        self._lock = threading.Lock()

    def next_block(self, n: int) -> Seq:
        """Reserve n consecutive numbers; return the first. They are IN FLIGHT until mark_applied."""
        with self._lock:
            first = self._last + 1
            self._last += n
            return first

    def mark_applied(self, first: Seq, n: int) -> None:
        """The block [first, first + n) is in the memtable. Blocks arrive in order (one writer)."""
        with self._lock:
            self._visible = first + n - 1

    @property
    def visible(self) -> Seq:
        """Every seq <= this is applied: the snapshot seq for a new query."""
        with self._lock:
            return self._visible

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
