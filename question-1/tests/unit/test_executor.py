"""QueryExecutor over one snapshot: memtables + real SSTables (seams Q1-Q5)."""

import random

import pytest

from tsdb.engine.version import Snapshot, Version
from tsdb.errors import QueryLimitError
from tsdb.faults import NoFaults
from tsdb.memtable.memtable import Memtable
from tsdb.memtable.skiplist import SkipList
from tsdb.model import Aggregation, Point, SeriesKey, TimeWindow, Tombstone
from tsdb.query.aggregate import AGGREGATORS
from tsdb.query.executor import QueryExecutor
from tsdb.sstable.bloom import BloomFilterFactory
from tsdb.sstable.factory import SSTableFactory
from tsdb.storage.fileio import OsFileOps
from tsdb.storage.layout import ShardLayout

MINUTE, SECOND = 60_000, 1_000
T = 1_730_368_800_000                                       # 10:00
W_10_00, W_10_02 = TimeWindow(MINUTE, T), TimeWindow(MINUTE, T + 2 * MINUTE)
KEYS = {1: SeriesKey.of("temperature", {"city": "Delhi"}), 2: SeriesKey.of("temperature", {"city": "Pune"}),
        3: SeriesKey.of("temperature", {"city": "Mumbai"})}


class FakeSeries:
    def key_of(self, series_id):
        return KEYS[series_id]


def memtable(*entries):
    m = Memtable(SkipList(random.Random(1)), 10**9, 100, 10**9)
    m.apply(list(entries))
    return m


@pytest.fixture
def snapshot(tmp_path):
    tables = SSTableFactory(ShardLayout(tmp_path).sstable, OsFileOps(), NoFaults(), BloomFilterFactory(), 4096, 0.01)

    def table(window, file_no, points):
        w = tables.new_writer(window, file_no)
        for p in points:
            w.add(p)
        return tables.open_reader(tables.publish(w.finish(), window, file_no), window)

    old = table(W_10_00, 1, [Point(1, T, 1, 30.1), Point(1, T + SECOND, 2, 30.2), Point(3, T, 3, 32.5)])
    later = table(W_10_02, 2, [Point(1, T + 2 * MINUTE + SECOND, 4, 31.5)])
    frozen = memtable(Point(1, T, 9, 29.9), Tombstone(10, (3,), T, T + MINUTE - 1))
    active = memtable(Point(3, T + 5 * SECOND, 12, 34.0), Point(1, T + 2 * MINUTE, 13, 31.0),
                      Point(1, T + 10 * SECOND, 14, 99.9))                     # seq 14: after the snapshot
    version = Version(3, active, (frozen,), ((W_10_00, (old,)), (W_10_02, (later,))), T)
    return Snapshot(version, seq=13)


def executor(snapshot, max_series=10_000, max_points=5_000_000):
    return QueryExecutor(snapshot, FakeSeries(), AGGREGATORS, max_series, max_points)


def test_q1_raw_points_merge_every_source_newest_wins_deletes_apply_and_to_is_inclusive(snapshot):
    result = executor(snapshot).run([1, 3], T, T + 2 * MINUTE, agg=None, bucket_ms=None)

    assert [(s.key, s.points) for s in result.series] == [
        (KEYS[1], [(T, 29.9),                    # frozen memtable seq 9 beats the file's seq 1
                   (T + SECOND, 30.2),            # only in the file
                   (T + 2 * MINUTE, 31.0)]),      # exactly `to`: included; seq 14 at 10:00:10 not seen
        (KEYS[3], [(T + 5 * SECOND, 34.0)]),      # 10:00 hidden by the delete; 10:00:05 written after it
    ]


def test_q1_a_series_with_no_points_in_range_is_left_out_like_an_empty_bucket(snapshot):
    result = executor(snapshot).run([1, 2], T + 30 * SECOND, T + 40 * SECOND, agg=None, bucket_ms=None)

    assert result.series == []                    # Delhi has nothing in 10:00:30-10:00:40, Pune never had data
