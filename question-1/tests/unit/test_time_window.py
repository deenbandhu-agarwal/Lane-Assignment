"""TimeWindow and Tombstone window behaviour (seams 1-6 in design-qa / TDD plan).

Expected values are worked examples written as literal epoch milliseconds, never recomputed
the way the code computes them.
"""

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
