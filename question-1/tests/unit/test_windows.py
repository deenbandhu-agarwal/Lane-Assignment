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

    groups = split_by_window(flush, [], MINUTE, live_windows=[])

    assert list(groups) == [W_10_00, W_10_01, W_10_02]       # windows in time order
    assert groups[W_10_00] == ([Point(1, T_10_00, 9, 29.9), Point(3, T_10_00 + 1, 3, 32.5)], [])
    assert groups[W_10_01] == ([Point(1, T_10_01 + 59_999, 4, 30.4), Point(2, T_10_01, 8, 28.2)], [])
    assert groups[W_10_02] == ([Point(1, T_10_02, 7, 31.0)], [])


def test_a_delete_is_cut_only_into_windows_that_may_hold_older_data():
    delete = Tombstone(10, (3,), T_10_00 + 30_000, T_10_02 + 15_000)
    point = Point(1, T_10_00, 9, 29.9)                         # this flush has data in 10:00 only

    groups = split_by_window([point], [delete], MINUTE, live_windows=[W_10_01])   # a file on disk for 10:01

    assert groups == {
        W_10_00: ([point], [Tombstone(10, (3,), T_10_00 + 30_000, T_10_01 - 1)]),
        W_10_01: ([], [Tombstone(10, (3,), T_10_01, T_10_02 - 1)]),        # delete-only file next to old data
    }                                                                       # 10:02: no data anywhere -> no piece


DAY = 24 * 60 * MINUTE
I64_MAX = 2**63 - 1


def test_an_all_time_delete_makes_one_piece_per_window_with_data_not_one_per_window_in_time():
    delete_all_time = Tombstone(20, (3,), 0, I64_MAX)
    day_file = TimeWindow(DAY, T_10_00 - T_10_00 % DAY)       # an old 1-day file already on disk

    groups = split_by_window([], [delete_all_time], MINUTE, live_windows=[day_file, W_10_01])

    assert groups == {
        day_file: ([], [Tombstone(20, (3,), day_file.start_ms, day_file.end_ms)]),   # ONE piece, not 1,440
        W_10_01: ([], [Tombstone(20, (3,), T_10_01, T_10_02 - 1)]),
    }


def test_nothing_to_flush_gives_no_windows():
    assert split_by_window([], [], MINUTE, live_windows=[W_10_00]) == {}
