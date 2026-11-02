"""Compactor with real files (seams K1-K2). 1-minute windows, numbers from the walkthrough example."""

import random

import pytest

from tsdb.compaction.compactor import Compactor
from tsdb.compaction.policy import CompactionJob, JobKind
from tsdb.engine.state import LiveState
from tsdb.engine.version import Version, VersionSet
from tsdb.faults import NoFaults
from tsdb.memtable.memtable import Memtable
from tsdb.memtable.skiplist import SkipList
from tsdb.model import ManifestState, Point, TimeWindow, Tombstone
from tsdb.sstable.bloom import BloomFilterFactory
from tsdb.sstable.factory import SSTableFactory
from tsdb.storage.fileio import OsFileOps
from tsdb.storage.layout import ShardLayout
from tsdb.storage.manifest import ManifestStore

MINUTE, SECOND = 60_000, 1_000
T = 1_730_368_800_000                              # 10:00
W_10_00 = TimeWindow(MINUTE, T)

A_POINTS = [Point(1, T, 1, 30.1), Point(2, T, 2, 28.0), Point(3, T, 3, 32.5), Point(3, T + SECOND, 4, 33.0)]
B_POINTS = [Point(1, T, 9, 29.9), Point(3, T + 2 * SECOND, 12, 34.0)]
DELETE_MUMBAI = Tombstone(10, (3,), T, T + 30 * SECOND)


class StopAt:
    def __init__(self, point):
        self.point = point

    def hit(self, point):
        if point == self.point:
            raise SystemExit(f"crash at {point}")


class Shard:
    def __init__(self, tmp_path, tables_in_window, faults=None):
        files, faults = OsFileOps(), faults or NoFaults()
        self.layout = ShardLayout(tmp_path)
        self.manifest = ManifestStore(self.layout.manifest, files, faults)
        self.tables = SSTableFactory(self.layout.sstable, files, faults, BloomFilterFactory(), 4096, 0.01)
        readers = []
        for file_no, (points, tombstones) in enumerate(tables_in_window, start=1):
            writer = self.tables.new_writer(W_10_00, file_no)
            for t in tombstones:
                writer.add_tombstone(t)
            for p in points:
                writer.add(p)
            readers.append(self.tables.open_reader(self.tables.publish(writer.finish(), W_10_00, file_no), W_10_00))
        self.readers = readers
        start = ManifestState(version=1, next_file_no=len(readers) + 1, last_flushed_seq=12, wal_segment=1, newest_data_ts=T, windows=((W_10_00, tuple(r.name for r in readers)),))
        self.manifest.commit(start)
        active = Memtable(SkipList(random.Random(1)), 10**9, 100, 10**9)
        self.versions = VersionSet(Version(1, active, (), ((W_10_00, tuple(reversed(readers))),), T),
                                   on_obsolete=lambda table: self.layout.sstable(W_10_00, int(table.name[:6])).unlink())
        self.state = LiveState(self.manifest, self.versions, start, active_segment=1)
        self.compactor = Compactor(self.versions, self.state, self.tables, faults)

    def job(self, *readers):
        return CompactionJob(JobKind.SIZE_TIERED, readers, W_10_00)


def test_k1_merge_keeps_only_the_newest_visible_points_and_drops_a_tombstone_nobody_else_needs(tmp_path):
    shard = Shard(tmp_path, [(A_POINTS, []), (B_POINTS, [DELETE_MUMBAI])])

    shard.compactor.run(shard.job(*shard.readers))

    [(window, (out,))] = shard.versions.current().windows
    assert list(out.iter_all()) == [
        Point(1, T, 9, 29.9),                       # newest version of (1, 10:00)
        Point(2, T, 2, 28.0),
        Point(3, T + 2 * SECOND, 12, 34.0),         # written after the delete: stays
    ]                                               # (3, 10:00) and (3, 10:00:01) hidden -> gone
    assert out.all_tombstones() == []               # every table it could hide is in this job
    assert shard.manifest.load().windows == ((W_10_00, ("000003.sst",)),)


def test_k1_a_tombstone_stays_while_a_table_outside_the_job_may_still_hold_hidden_data(tmp_path):
    outside = ([Point(3, T + 5 * SECOND, 5, 31.0)], [])          # another file in the window, not in the job
    shard = Shard(tmp_path, [(A_POINTS, []), (B_POINTS, [DELETE_MUMBAI]), outside])

    shard.compactor.run(shard.job(shard.readers[0], shard.readers[1]))

    out = next(t for _, tables in shard.versions.current().windows for t in tables if t.name == "000004.sst")
    assert out.all_tombstones() == [DELETE_MUMBAI]               # still needed to hide (3, 10:00:05, seq 5)


def sst_files(tmp_path):
    return sorted(p.name for p in (tmp_path / "sst").rglob("*.sst"))


def test_k2_after_a_successful_swap_only_the_output_is_live_and_the_inputs_are_deleted(tmp_path):
    shard = Shard(tmp_path, [(A_POINTS, []), (B_POINTS, [DELETE_MUMBAI])])

    shard.compactor.run(shard.job(*shard.readers))

    assert shard.manifest.load().windows == ((W_10_00, ("000003.sst",)),)
    assert sst_files(tmp_path) == ["000003.sst"]


def test_k2_a_running_query_keeps_the_inputs_until_it_ends(tmp_path):
    shard = Shard(tmp_path, [(A_POINTS, []), (B_POINTS, [DELETE_MUMBAI])])
    query = shard.versions.acquire(seq=12)

    shard.compactor.run(shard.job(*shard.readers))

    assert sst_files(tmp_path) == ["000001.sst", "000002.sst", "000003.sst"]
    shard.versions.release(query)
    assert sst_files(tmp_path) == ["000003.sst"]


def test_k2_a_crash_at_the_swap_leaves_all_inputs_live_and_the_output_unlisted(tmp_path):
    shard = Shard(tmp_path, [(A_POINTS, []), (B_POINTS, [DELETE_MUMBAI])], faults=StopAt("compaction_swap"))

    with pytest.raises(SystemExit):
        shard.compactor.run(shard.job(*shard.readers))

    assert shard.manifest.load().windows == ((W_10_00, ("000001.sst", "000002.sst")),)   # never both
    assert [t.name for _, ts in shard.versions.current().windows for t in ts] == ["000002.sst", "000001.sst"]
    assert sst_files(tmp_path) == ["000001.sst", "000002.sst", "000003.sst"]   # 000003 = orphan for recovery
