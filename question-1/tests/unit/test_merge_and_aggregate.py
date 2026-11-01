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
