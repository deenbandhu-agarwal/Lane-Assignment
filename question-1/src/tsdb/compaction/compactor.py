"""Run one CompactionJob. Depends only on ports.

    1. k-way merge all input tables in key order (query.merge)
    2. per key keep only the highest seq (older versions dropped)
    3. drop points hidden by tombstones (Rule 1)
    4. Rule 2 for every tombstone: drop it only if no live table outside the job may hold one of
       its series in its range (memtables never can: design-qa #43); otherwise keep it.
    5. write ONE output table in job.output_window via TableFactory (.tmp -> publish); no output
       file if nothing is left (everything deleted, every tombstone dropped)
    6. LiveState.commit(Edit): inputs out, output in      -> hit(COMPACTION_SWAP) just before it
    7. inputs are deleted by VersionSet when no snapshot uses them any more
Proof obligations (tests): no point lost or duplicated after repeated runs; no zombie data;
crash at the swap leaves either all inputs or the output live, never both or neither.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterator

from tsdb.compaction.policy import CompactionJob
from tsdb.engine.state import Edit, LiveState
from tsdb.engine.version import Version, VersionSet
from tsdb.faults import CrashPoint
from tsdb.model import Point, Tombstone
from tsdb.ports import FaultInjector, TableFactory


def tombstone_droppable(tombstone: Tombstone, job: CompactionJob, version: Version) -> bool:
    """Rule 2 as a pure function, unit-tested on its own.
    Drop only if no live table OUTSIDE the job may hold a point of these series in the range.
    Memtables are not checked: this tombstone was flushed, so every memtable entry has a bigger
    seq and cannot be hidden by it (design-qa #43)."""
    in_job = {table.name for table in job.inputs}
    for _, tables in version.windows:
        for table in tables:
            if table.name in in_job:
                continue
            if any(table.may_contain(s, tombstone.from_ts, tombstone.to_ts) for s in tombstone.series_ids):
                return False
    return True


class Compactor:
    def __init__(self, versions: VersionSet, state: LiveState, tables: TableFactory,
                 faults: FaultInjector) -> None:
        self._versions = versions
        self._state = state
        self._tables = tables
        self._faults = faults

    def run(self, job: CompactionJob) -> None:
        version = self._versions.current()
        tombstones = list(dict.fromkeys(t for table in job.inputs for t in table.all_tombstones()))
        by_series: dict[int, list[Tombstone]] = {}
        for t in tombstones:
            for series_id in t.series_ids:
                by_series.setdefault(series_id, []).append(t)
        kept = [t for t in tombstones if not tombstone_droppable(t, job, version)]

        file_no = self._state.allocate_file_no()
        writer = self._tables.new_writer(job.output_window, file_no)
        for t in kept:
            writer.add_tombstone(t)
        written = 0
        for p in _newest_per_key(job.inputs):
            if not any(t.hides(p.series_id, p.timestamp, p.seq) for t in by_series.get(p.series_id, ())):
                writer.add(p)
                written += 1
        added = ()
        if written or kept:
            final = self._tables.publish(writer.finish(), job.output_window, file_no)
            added = ((job.output_window, self._tables.open_reader(final, job.output_window)),)
        else:
            writer.abort()
        self._faults.hit(CrashPoint.COMPACTION_SWAP)
        self._state.commit(Edit(added=added, removed=frozenset(t.name for t in job.inputs)))


def _newest_per_key(tables) -> Iterator[Point]:
    """k-way merge of all inputs by (series, timestamp, newest first); one point per key."""
    merged = heapq.merge(*(t.iter_all() for t in tables), key=lambda p: (p.series_id, p.timestamp, -p.seq))
    last = None
    for p in merged:
        if (p.series_id, p.timestamp) != last:
            last = (p.series_id, p.timestamp)
            yield p
