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


def test_flush_gets_only_the_newest_version_of_each_point_in_key_order(mem):
    assert list(mem.iter_for_flush()) == [
        Point(1, T_10_00, 9, 29.9),      # seq 1 (30.1) dropped: last write wins
        Point(1, T_10_01, 4, 30.4),
        Point(1, T_10_02, 7, 31.0),
        Point(2, T_10_00, 2, 28.0),
        Point(2, T_10_01, 8, 28.2),      # seq 5 (28.1) dropped
        Point(3, T_10_00, 3, 32.5),      # still here: the delete is applied by readers, and the
        Point(3, T_10_01, 6, 32.9),      # tombstone goes into the file next to these points
    ]
    assert mem.all_tombstones() == [DELETE_MUMBAI]


def test_a_delete_over_several_series_is_listed_once_for_flush():
    m = new_memtable()
    both = Tombstone(11, (1, 2), T_10_00, T_10_02)
    m.apply([both])

    assert m.all_tombstones() == [both]


def test_a_frozen_memtable_refuses_writes_but_still_answers_reads(mem):
    mem.freeze()

    with pytest.raises(RuntimeError):
        mem.apply([Point(1, T_10_02, 11, 1.0)])
    assert list(mem.read_series(1, T_10_02, T_10_02, snapshot_seq=10)) == [Point(1, T_10_02, 7, 31.0)]


def test_full_when_the_size_estimate_reaches_the_limit():
    m = new_memtable(max_bytes=500, entry_bytes=100)          # 5 entries x 100 B
    m.apply(STEP1[:4])
    assert not m.is_full()

    m.apply([DELETE_MUMBAI])                                  # a tombstone counts as one entry
    assert m.is_full()


def test_full_when_the_entry_cap_is_reached_first():
    m = new_memtable(max_entries=3)
    m.apply(STEP1[:2])
    assert not m.is_full()

    m.apply(STEP1[2:3])
    assert m.is_full()


def test_max_seq_follows_every_write_and_max_timestamp_only_data(mem):
    assert mem.max_seq == 10                                  # the delete
    assert mem.max_timestamp == T_10_02                       # newest POINT time

    mem.apply([Tombstone(12, (1,), T_10_00, T_10_02 + 3_600_000)])   # a delete reaching 1 h ahead

    assert (mem.max_seq, mem.max_timestamp) == (12, T_10_02)  # must not close windows early
