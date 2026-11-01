"""Merge-on-read for one series, and streaming bucket aggregation (seams 1-5).
Numbers follow the walkthrough example."""

import pytest

from tsdb.model import Point, Tombstone
from tsdb.query.merge import merge_series

T_10_00 = 1_730_368_800_000
T_10_01 = 1_730_368_860_000
T_10_02 = 1_730_368_920_000


def test_the_newest_seq_wins_and_each_timestamp_comes_back_once():
    file_000001 = iter([Point(1, T_10_00, 1, 30.1), Point(1, T_10_01, 4, 30.4)])
    memtable = iter([Point(1, T_10_00, 9, 29.9), Point(1, T_10_02, 7, 31.0)])

    assert list(merge_series([file_000001, memtable], tombstones=[])) == [
        Point(1, T_10_00, 9, 29.9),
        Point(1, T_10_01, 4, 30.4),
        Point(1, T_10_02, 7, 31.0),
    ]


def test_order_of_sources_does_not_matter():
    a = [Point(1, T_10_00, 1, 30.1)]
    b = [Point(1, T_10_00, 9, 29.9)]

    assert list(merge_series([iter(b), iter(a)], [])) == list(merge_series([iter(a), iter(b)], [])) \
        == [Point(1, T_10_00, 9, 29.9)]


DELETE_MUMBAI = Tombstone(10, (3,), T_10_00, T_10_01)


def test_a_delete_hides_older_points_but_not_later_writes_or_times_outside_it():
    file_000001 = iter([Point(3, T_10_00, 3, 32.5), Point(3, T_10_01, 6, 32.9), Point(3, T_10_02, 8, 33.0)])
    memtable = iter([Point(3, T_10_00, 12, 30.0)])           # written AFTER the delete

    assert list(merge_series([file_000001, memtable], [DELETE_MUMBAI])) == [
        Point(3, T_10_00, 12, 30.0),                          # newer than the delete: visible
        Point(3, T_10_02, 8, 33.0),                           # outside the delete range: visible
    ]


def test_when_the_newest_version_is_hidden_an_older_version_never_comes_back():
    older_file = iter([Point(3, T_10_00, 3, 32.5)])
    newer_file = iter([Point(3, T_10_00, 8, 31.0)])

    assert list(merge_series([older_file, newer_file], [DELETE_MUMBAI])) == []
