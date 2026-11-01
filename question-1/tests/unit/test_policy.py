"""TimeWindowPolicy.pick (seams P1-P3). Steps 1 h -> 6 h -> 1 day, merge at 4, late merge at 10%."""

from tsdb.compaction.policy import JobKind, TimeWindowPolicy
from tsdb.engine.version import Version
from tsdb.model import TimeWindow

HOUR = 3_600_000
SIX_HOURS, DAY = 6 * HOUR, 24 * HOUR
T_00_00 = 1_730_332_800_000                     # 2024-10-31 midnight UTC
T_06_00 = T_00_00 + 6 * HOUR
T_10_00 = T_00_00 + 10 * HOUR


def hour(h):
    return TimeWindow(HOUR, T_00_00 + h * HOUR)


W_06_12 = TimeWindow(SIX_HOURS, T_06_00)


class FakeTable:
    def __init__(self, name, size_bytes=1_000):
        self.name, self.size_bytes = name, size_bytes

    def __repr__(self):
        return self.name


def version(windows, newest_data_ts):
    return Version(1, None, (), tuple(sorted(windows.items(), key=lambda i: (i[0].start_ms, i[0].size_ms))),
                   newest_data_ts)


POLICY = TimeWindowPolicy((HOUR, SIX_HOURS, DAY), merge_threshold=4, late_merge_ratio=0.10,
                          late_merge_interval_ms=DAY)
NOW_10_30 = T_10_00 + 30 * 60_000               # newest data time: 10:00 hour still open


def names(job):
    return sorted(t.name for t in job.inputs)


def test_p1_four_files_in_one_hour_are_merged_and_three_are_not():
    three = {hour(10): (FakeTable("a"), FakeTable("b"), FakeTable("c"))}
    four = {hour(10): (FakeTable("a"), FakeTable("b"), FakeTable("c"), FakeTable("d"))}

    assert POLICY.pick(version(three, NOW_10_30)) is None
    job = POLICY.pick(version(four, NOW_10_30))
    assert (job.kind, job.output_window, names(job)) == (JobKind.SIZE_TIERED, hour(10), ["a", "b", "c", "d"])
