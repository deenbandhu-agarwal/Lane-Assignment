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
        self._lock = threading.Lock()

    def next_block(self, n: int) -> Seq:
        """Reserve n consecutive numbers; return the first. They are IN FLIGHT until mark_applied."""
        raise NotImplementedError

    def mark_applied(self, first: Seq, n: int) -> None:
        """The block [first, first + n) is in the memtable; may raise `visible`."""
        raise NotImplementedError

    @property
    def visible(self) -> Seq:
        """Every seq <= this is applied: the snapshot seq for a new query."""
        raise NotImplementedError

    def wait_until_visible(self, seq: Seq) -> None:
        raise NotImplementedError

    def observe(self, seen: Seq) -> None:
        raise NotImplementedError

    @property
    def last(self) -> Seq:
        """Highest number handed out (MANIFEST / recovery). NOT a snapshot seq: use `visible`."""
        raise NotImplementedError
