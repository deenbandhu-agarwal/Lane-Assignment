"""Memtable (seams 1-4). Numbers follow the walkthrough example: series 1 at 10:00 is written with
seq 1 (30.1) and later overwritten with seq 9 (29.9); series 3 gets a delete with seq 10."""

import random

import pytest

from tsdb.memtable.memtable import Memtable
from tsdb.memtable.skiplist import SkipList
from tsdb.model import Point, Tombstone

T_10_00 = 1_730_368_800_000
T_10_01 = 1_730_368_860_000
T_10_02 = 1_730_368_920_000

STEP1 = [Point(1, T_10_00, 1, 30.1), Point(2, T_10_00, 2, 28.0), Point(3, T_10_00, 3, 32.5),
         Point(1, T_10_01, 4, 30.4), Point(2, T_10_01, 5, 28.1), Point(3, T_10_01, 6, 32.9)]
STEP3 = [Point(1, T_10_02, 7, 31.0), Point(2, T_10_01, 8, 28.2), Point(1, T_10_00, 9, 29.9)]
DELETE_MUMBAI = Tombstone(10, (3,), T_10_00, T_10_01)


def new_memtable(max_bytes=10**9, entry_bytes=100, max_entries=10**9) -> Memtable:
    return Memtable(SkipList(random.Random(140)), max_bytes, entry_bytes, max_entries)


@pytest.fixture
def mem():
    m = new_memtable()
    m.apply(STEP1)
    m.apply(STEP3)
    m.apply([DELETE_MUMBAI])
    return m


def test_a_snapshot_sees_the_newest_version_written_at_or_before_it(mem):
    whole = (T_10_00, T_10_02)

    assert list(mem.read_series(1, *whole, snapshot_seq=5)) == [Point(1, T_10_00, 1, 30.1),
                                                                Point(1, T_10_01, 4, 30.4)]
    assert list(mem.read_series(1, *whole, snapshot_seq=10)) == [Point(1, T_10_00, 9, 29.9),
                                                                 Point(1, T_10_01, 4, 30.4),
                                                                 Point(1, T_10_02, 7, 31.0)]


def test_a_read_returns_only_its_series_and_time_range(mem):
    assert list(mem.read_series(2, T_10_01, T_10_01, snapshot_seq=10)) == [Point(2, T_10_01, 8, 28.2)]
    assert list(mem.read_series(4, T_10_00, T_10_02, snapshot_seq=10)) == []


def test_a_delete_is_visible_only_to_snapshots_taken_after_it(mem):
    assert mem.tombstones_for(3, snapshot_seq=9) == []
    assert mem.tombstones_for(3, snapshot_seq=10) == [DELETE_MUMBAI]
    assert mem.tombstones_for(1, snapshot_seq=10) == []
