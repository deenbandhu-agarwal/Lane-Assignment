"""Rule 2: may compaction drop a tombstone? (seams R1-R3)

Drop only if NO live table outside the job may hold a point the tombstone hides. Memtables are not
checked: a tombstone inside a file was flushed, so every memtable entry has a bigger seq and can
never be hidden by it (design-qa #43)."""

from tsdb.compaction.compactor import tombstone_droppable
from tsdb.compaction.policy import CompactionJob, JobKind
from tsdb.engine.version import Version
from tsdb.model import TimeWindow, Tombstone

HOUR = 3_600_000
SIX_HOURS = 6 * HOUR
T_06_00 = 1_730_354_400_000
T_10_00 = 1_730_368_800_000
T_11_00 = 1_730_372_400_000
W_10 = TimeWindow(HOUR, T_10_00)
W_11 = TimeWindow(HOUR, T_11_00)
W_06_12 = TimeWindow(SIX_HOURS, T_06_00)


class FakeTable:
    """Answers may_contain from a fixed set of series and a time range, like footer + Bloom."""

    def __init__(self, name, series, min_ts, max_ts):
        self.name, self._series, self.min_ts, self.max_ts = name, set(series), min_ts, max_ts

    def may_contain(self, series_id, from_ts, to_ts):
        return series_id in self._series and from_ts <= self.max_ts and to_ts >= self.min_ts


def version(*windows):
    return Version(number=1, active=None, immutables=(), windows=windows, newest_data_ts=T_11_00)


DELETE_MUMBAI = Tombstone(10, (3,), T_10_00 + 30 * 60_000, T_10_00 + 45 * 60_000)   # 10:30-10:45

A = FakeTable("000001.sst", {1, 2, 3}, T_10_00, T_10_00 + HOUR - 1)
B = FakeTable("000002.sst", {1, 3}, T_10_00, T_10_00 + HOUR - 1)
NEXT_HOUR = FakeTable("000003.sst", {1, 2, 3}, T_11_00, T_11_00 + HOUR - 1)


def job(*inputs, window=W_10):
    return CompactionJob(JobKind.SIZE_TIERED, inputs, window)


def test_r1_dropped_when_the_job_holds_every_table_that_could_hide_data():
    v = version((W_10, (A, B)), (W_11, (NEXT_HOUR,)))       # other hour does not overlap 10:30-10:45

    assert tombstone_droppable(DELETE_MUMBAI, job(A, B), v)
