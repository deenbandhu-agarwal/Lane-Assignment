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


def test_a_delete_is_cut_into_every_window_it_covers_even_windows_without_points():
    delete = Tombstone(10, (3,), T_10_00 + 30_000, T_10_02 + 15_000)
    point = Point(1, T_10_00, 9, 29.9)

    groups = split_by_window([point], [delete], MINUTE)

    assert groups == {
        W_10_00: ([point], [Tombstone(10, (3,), T_10_00 + 30_000, T_10_01 - 1)]),
        W_10_01: ([], [Tombstone(10, (3,), T_10_01, T_10_02 - 1)]),        # only a delete piece
        W_10_02: ([], [Tombstone(10, (3,), T_10_02, T_10_02 + 15_000)]),
    }
    assert list(groups) == [W_10_00, W_10_01, W_10_02]


def test_nothing_to_flush_gives_no_windows():
    assert split_by_window([], [], MINUTE) == {}
