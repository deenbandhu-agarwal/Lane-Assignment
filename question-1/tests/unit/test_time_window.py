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
