"""Flush end to end with real files (seams F1-F2). 1-minute smallest windows, as in the example."""

import random

import pytest

from tsdb.engine.flush import Flusher
from tsdb.engine.state import LiveState
from tsdb.engine.swap_lock import SwapLock
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

MINUTE = 60_000
T_10_00 = 1_730_368_800_000
T_10_01 = 1_730_368_860_000
W_10_00, W_10_01 = TimeWindow(MINUTE, T_10_00), TimeWindow(MINUTE, T_10_01)


def new_memtable():
    return Memtable(SkipList(random.Random(140)), 10**9, 100, 10**9)


class FakeWal:
    """Stands in for WalSet: rotate_all hands back the old segment files (which exist on disk)."""

    def __init__(self, layout):
        self.layout, self.rotations = layout, []

    def rotate_all(self, new_segment_no, new_memtable):
        old = self.layout.wal_segment(0, new_segment_no - 1)
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_bytes(b"old wal bytes")
        self.rotations.append((new_segment_no, new_memtable))
        return [old]


class Shard:
    """The flush pieces wired the way bootstrap will wire them."""

    def __init__(self, tmp_path, faults=None):
        files, faults = OsFileOps(), faults or NoFaults()
        self.layout = ShardLayout(tmp_path)
        self.manifest = ManifestStore(self.layout.manifest, files, faults)
        self.tables = SSTableFactory(self.layout.sstable, files, faults, BloomFilterFactory(), 4096, 0.01)
        self.active = new_memtable()
        self.versions = VersionSet(Version(0, self.active, (), (), 0), on_obsolete=lambda t: None)
        start = ManifestState(version=0, next_file_no=1, last_flushed_seq=0, wal_count=1, wal_segment=1)
        self.state = LiveState(self.manifest, self.versions, start, active_segment=1)
        self.wal = FakeWal(self.layout)
        self.flusher = Flusher(self.versions, self.wal, self.state, self.tables, new_memtable, files, faults,
                               SwapLock(), smallest_window_ms=MINUTE)


STEP1 = [Point(1, T_10_00, 1, 30.1), Point(2, T_10_00, 2, 28.0), Point(3, T_10_00, 3, 32.5),
         Point(1, T_10_01, 4, 30.4), Point(2, T_10_01, 5, 28.1), Point(3, T_10_01, 6, 32.9)]
DELETE_MUMBAI = Tombstone(7, (3,), T_10_00, T_10_01)


def test_a_swap_freezes_the_memtable_and_keeps_it_readable_next_to_the_new_one(tmp_path):
    shard = Shard(tmp_path)
    shard.active.apply(STEP1)

    frozen = shard.flusher.swap_memtable()

    v = shard.versions.current()
    assert frozen is shard.active
    assert v.immutables == (frozen,)                     # still readable while it is flushed
    assert v.active is not frozen and shard.wal.rotations == [(2, v.active)]
    with pytest.raises(RuntimeError):
        frozen.apply([Point(1, T_10_00, 99, 0.0)])


def test_a_flush_writes_one_file_per_window_and_makes_them_live_in_manifest_and_version(tmp_path):
    shard = Shard(tmp_path)
    shard.active.apply(STEP1 + [DELETE_MUMBAI])
    frozen = shard.flusher.swap_memtable()

    shard.flusher.flush(frozen)

    v = shard.versions.current()
    assert v.immutables == ()                            # the frozen memtable is replaced by its files
    assert [w for w, _ in v.windows] == [W_10_00, W_10_01]
    [f1], [f2] = (tables for _, tables in v.windows)
    assert list(f1.iter_all()) == STEP1[0:3] and list(f2.iter_all()) == STEP1[3:6]
    assert f1.all_tombstones() == [Tombstone(7, (3,), T_10_00, T_10_01 - 1)]
    assert f2.all_tombstones() == [Tombstone(7, (3,), T_10_01, T_10_01)]
    assert (tmp_path / "sst" / "60000" / str(T_10_00) / "000001.sst").exists()

    state = shard.manifest.load()
    assert state.windows == ((W_10_00, ("000001.sst",)), (W_10_01, ("000002.sst",)))
    assert (state.next_file_no, state.last_flushed_seq, state.newest_data_ts, state.wal_segment) \
        == (3, 7, T_10_01, 2)                            # replay starts at segment 2 from now on
    assert not shard.layout.wal_segment(0, 1).exists()   # the flushed WAL segment is gone


def test_a_second_flush_adds_to_the_windows_already_there(tmp_path):
    shard = Shard(tmp_path)
    shard.active.apply(STEP1[:3])
    shard.flusher.flush(shard.flusher.swap_memtable())
    shard.versions.current().active.apply([Point(1, T_10_00, 8, 29.9)])   # overwrite at 10:00

    shard.flusher.flush(shard.flusher.swap_memtable())

    [(window, tables)] = shard.versions.current().windows
    assert window == W_10_00
    assert [t.name for t in tables] == ["000002.sst", "000001.sst"]       # newest first
    assert shard.manifest.load().windows == ((W_10_00, ("000001.sst", "000002.sst")),)
