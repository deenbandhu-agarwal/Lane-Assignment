"""Flush split by window (S1-S2). 1-minute smallest windows, as in the walkthrough example."""

from tsdb.engine.flush import split_by_window
from tsdb.model import Point, TimeWindow, Tombstone

MINUTE = 60_000
T_10_00 = 1_730_368_800_000
T_10_01 = 1_730_368_860_000
T_10_02 = 1_730_368_920_000
W_10_00, W_10_01, W_10_02 = (TimeWindow(MINUTE, t) for t in (T_10_00, T_10_01, T_10_02))


def test_points_are_grouped_by_their_smallest_window_and_keep_their_order():
    flush = [Point(1, T_10_00, 9, 29.9), Point(1, T_10_01 + 59_999, 4, 30.4), Point(1, T_10_02, 7, 31.0),
             Point(2, T_10_01, 8, 28.2),                       # late point for an earlier window
             Point(3, T_10_00 + 1, 3, 32.5)]

    groups = split_by_window(flush, [], MINUTE)

    assert list(groups) == [W_10_00, W_10_01, W_10_02]       # windows in time order
    assert groups[W_10_00] == ([Point(1, T_10_00, 9, 29.9), Point(3, T_10_00 + 1, 3, 32.5)], [])
    assert groups[W_10_01] == ([Point(1, T_10_01 + 59_999, 4, 30.4), Point(2, T_10_01, 8, 28.2)], [])
    assert groups[W_10_02] == ([Point(1, T_10_02, 7, 31.0)], [])
