"""Merge-on-read for one series, and streaming bucket aggregation (seams 1-5).
Numbers follow the walkthrough example."""

import pytest

from tsdb.model import Point, Tombstone
from tsdb.query.aggregate import BucketAggregator
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


class Values:
    """Fake aggregator: result is the tuple of values it saw (shows exactly what went where)."""

    def __init__(self):
        self.seen = []

    def add(self, value):
        self.seen.append(value)

    def result(self):
        return tuple(self.seen)


MINUTE = 60_000
T_10_00_30 = T_10_00 + 30_000
T_10_00_59_999 = T_10_01 - 1


def test_buckets_are_aligned_to_the_epoch_and_the_first_may_start_before_from():
    points = iter([Point(1, T_10_00_30, 1, 1.0), Point(1, T_10_00_59_999, 2, 2.0),
                   Point(1, T_10_01, 3, 3.0)])

    assert BucketAggregator(Values, MINUTE, from_ts=T_10_00_30).run(points) == [
        (T_10_00, (1.0, 2.0)),                # bucket 10:00:00 although `from` is 10:00:30
        (T_10_01, (3.0,)),                    # 10:01:00.000 starts the next bucket
    ]


def test_empty_buckets_are_left_out():
    points = iter([Point(1, T_10_00, 1, 1.0), Point(1, T_10_02, 2, 2.0)])

    assert [start for start, _ in BucketAggregator(Values, MINUTE, T_10_00).run(points)] == [T_10_00, T_10_02]


def test_no_bucket_size_means_one_value_for_the_whole_range_keyed_by_from():
    points = iter([Point(1, T_10_00_30, 1, 1.0), Point(1, T_10_02, 2, 2.0)])

    assert BucketAggregator(Values, None, from_ts=T_10_00).run(points) == [(T_10_00, (1.0, 2.0))]


def test_no_points_gives_no_buckets():
    assert BucketAggregator(Values, None, T_10_00).run(iter([])) == []
