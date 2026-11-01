"""Startup recovery with real files (seams R1-R5)."""

import random

import pytest

from tsdb.engine.recovery import Recovery
from tsdb.faults import NoFaults
from tsdb.memtable.memtable import Memtable
from tsdb.memtable.skiplist import SkipList
from tsdb.model import ManifestState, Point, TimeWindow, Tombstone
from tsdb.sstable.bloom import BloomFilterFactory
from tsdb.sstable.factory import SSTableFactory
from tsdb.storage.fileio import OsFileOps
from tsdb.storage.layout import ShardLayout
from tsdb.storage.manifest import ManifestStore
from tsdb.wal.record import encode_delete, encode_put, frame
from tsdb.wal.wal_set import WalReplayer

MINUTE = 60_000
T = 1_730_368_800_000
W_10_00 = TimeWindow(MINUTE, T)


class FakeSeries:
    def __init__(self):
        self.loaded = 0

    def load(self):
        self.loaded += 1


def new_memtable():
    return Memtable(SkipList(random.Random(1)), 10**9, 100, 10**9)


class Dir:
    def __init__(self, tmp_path, wal_count=1):
        files = OsFileOps()
        self.root, self.layout, self.files = tmp_path, ShardLayout(tmp_path), files
        self.manifest = ManifestStore(self.layout.manifest, files, NoFaults())
        self.tables = SSTableFactory(self.layout.sstable, files, NoFaults(), BloomFilterFactory(), 4096, 0.01)
        self.series = FakeSeries()
        self.wal_count = wal_count

    def recover(self, wal_count=None):
        replayer = WalReplayer(self.files, self.layout.wal_segment)
        return Recovery(self.layout, self.manifest, self.series, self.tables, replayer.replay, new_memtable,
                        self.files, wal_count or self.wal_count).run()

    def wal(self, segment, *entries, wal=0):
        path = self.layout.wal_segment(wal, segment)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(frame(encode_put(e) if isinstance(e, Point) else encode_delete(e)) for e in entries))
        return path

    def table(self, file_no, points):
        writer = self.tables.new_writer(W_10_00, file_no)
        for p in points:
            writer.add(p)
        return self.tables.publish(writer.finish(), W_10_00, file_no)


def test_r1_an_empty_directory_starts_empty(tmp_path):
    state = Dir(tmp_path).recover()

    assert (state.last_seq, state.windows, state.manifest.wal_segment, state.active_segment) == (0, (), 1, 1)
    assert list(state.memtable.iter_for_flush()) == []


def test_r2_acknowledged_writes_and_deletes_come_back_from_the_wal(tmp_path):
    d = Dir(tmp_path)
    d.wal(1, Point(1, T, 1, 30.1), Point(3, T, 2, 32.5), Tombstone(3, (3,), T, T + MINUTE - 1),
          Point(1, T + 1_000, 4, 30.4))

    state = d.recover()

    assert list(state.memtable.read_series(1, T, T + MINUTE, snapshot_seq=4)) == [Point(1, T, 1, 30.1),
                                                                                   Point(1, T + 1_000, 4, 30.4)]
    assert state.memtable.tombstones_for(3, snapshot_seq=4) == [Tombstone(3, (3,), T, T + MINUTE - 1)]
    assert state.last_seq == 4
    assert state.memtable.max_timestamp == T + 1_000
    assert state.active_segment == 2                     # new writes go to a fresh segment
    assert d.series.loaded == 1


def test_r3_after_a_flush_files_come_from_the_manifest_and_only_newer_wal_segments_are_replayed(tmp_path):
    d = Dir(tmp_path)
    d.table(1, [Point(1, T, 1, 30.1), Point(3, T, 2, 32.5)])
    d.manifest.commit(ManifestState(version=1, next_file_no=2, last_flushed_seq=2, wal_count=1, wal_segment=2,
                                    newest_data_ts=T, windows=((W_10_00, ("000001.sst",)),)))
    old = d.wal(1, Point(1, T, 1, 30.1), Point(3, T, 2, 32.5))     # crash right after the commit:
    d.wal(2, Point(1, T, 3, 29.9))                                  # segment 1 was not deleted yet

    state = d.recover()

    [(window, (table,))] = state.windows
    assert (window, table.name) == (W_10_00, "000001.sst")
    assert list(table.iter_all()) == [Point(1, T, 1, 30.1), Point(3, T, 2, 32.5)]
    assert list(state.memtable.iter_for_flush()) == [Point(1, T, 3, 29.9)]    # segment 1 NOT replayed again
    assert state.last_seq == 3
    assert not old.exists()                                          # already flushed: deleted
    assert state.active_segment == 3
