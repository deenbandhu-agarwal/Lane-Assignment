"""TimeWindow and Tombstone window behaviour (seams 1-6 in design-qa / TDD plan).

Expected values are worked examples written as literal epoch milliseconds, never recomputed
the way the code computes them.
"""

import pytest

from tsdb.model import TimeWindow

HOUR = 3_600_000

# 2024-10-31 UTC
T_10_00_00_000 = 1_730_368_800_000
T_10_37_12_345 = 1_730_371_032_345
T_10_59_59_999 = 1_730_372_399_999


def test_window_containing_a_timestamp_starts_on_the_epoch_aligned_boundary_and_ends_inclusive():
    w = TimeWindow.containing(T_10_37_12_345, HOUR)

    assert w.start_ms == T_10_00_00_000
    assert w.end_ms == T_10_59_59_999


T_09_59_59_999 = 1_730_368_799_999
T_11_00_00_000 = 1_730_372_400_000


def test_window_contains_its_first_and_last_millisecond_but_not_its_neighbours():
    w = TimeWindow(HOUR, T_10_00_00_000)

    assert w.contains(T_10_00_00_000)
    assert w.contains(T_10_59_59_999)
    assert not w.contains(T_09_59_59_999)
    assert not w.contains(T_11_00_00_000)


T_09_00_00_000 = 1_730_365_200_000
T_12_00_00_000 = 1_730_376_000_000


def test_window_overlaps_ranges_that_touch_its_edges_and_not_ranges_just_outside():
    w = TimeWindow(HOUR, T_10_00_00_000)

    assert w.overlaps(T_09_00_00_000, T_10_00_00_000)        # ends on our first ms
    assert w.overlaps(T_10_59_59_999, T_12_00_00_000)        # starts on our last ms
    assert w.overlaps(T_09_00_00_000, T_12_00_00_000)        # covers us completely
    assert w.overlaps(T_10_37_12_345, T_10_37_12_345)        # single point inside
    assert not w.overlaps(T_09_00_00_000, T_09_59_59_999)    # ends just before
    assert not w.overlaps(T_11_00_00_000, T_12_00_00_000)    # starts just after


SIX_HOURS = 6 * HOUR
DAY = 24 * HOUR
T_00_00_00_000 = 1_730_332_800_000   # 2024-10-31 midnight UTC
T_06_00_00_000 = 1_730_354_400_000


def test_an_hour_window_has_exactly_one_six_hour_parent_and_one_day_parent():
    w = TimeWindow(HOUR, T_10_00_00_000)

    assert w.parent(SIX_HOURS) == TimeWindow(SIX_HOURS, T_06_00_00_000)
    assert w.parent(DAY) == TimeWindow(DAY, T_00_00_00_000)


def test_a_six_hour_window_splits_into_its_six_hour_long_children_in_order():
    w = TimeWindow(SIX_HOURS, T_06_00_00_000)

    assert [c.start_ms for c in w.children(HOUR)] == [
        1_730_354_400_000,   # 06:00
        1_730_358_000_000,   # 07:00
        1_730_361_600_000,   # 08:00
        1_730_365_200_000,   # 09:00
        1_730_368_800_000,   # 10:00
        1_730_372_400_000,   # 11:00
    ]
    assert all(c.size_ms == HOUR for c in w.children(HOUR))


def test_sizes_that_do_not_nest_are_rejected():
    w = TimeWindow(HOUR, T_10_00_00_000)
    with pytest.raises(ValueError):
        w.parent(90 * 60_000)            # 1.5 h is not a multiple of 1 h
    with pytest.raises(ValueError):
        w.parent(30 * 60_000)            # a parent must be bigger
    with pytest.raises(ValueError):
        w.children(25 * 60_000)          # 25 min does not divide 1 h
