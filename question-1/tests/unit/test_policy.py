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


SIX_HOURS_OF_FILES = {hour(h): (FakeTable(f"h{h}"),) for h in range(6, 12)}   # one file per hour 06..11
T_12_59_59_999 = T_00_00 + 13 * HOUR - 1
T_13_00 = T_00_00 + 13 * HOUR


def test_p2_six_closed_hours_move_up_into_their_six_hour_window():
    # 06:00-12:00 ends 11:59:59.999; grace one hour -> closed once newest data is past 12:59:59.999
    job = POLICY.pick(version(SIX_HOURS_OF_FILES, T_13_00))

    assert (job.kind, job.output_window) == (JobKind.MOVE_UP, W_06_12)
    assert names(job) == ["h10", "h11", "h6", "h7", "h8", "h9"]


def test_p2_no_move_up_while_the_last_hour_can_still_get_writes():
    assert POLICY.pick(version(SIX_HOURS_OF_FILES, T_12_59_59_999)) is None


def test_p2_four_closed_days_of_six_hour_files_move_up_into_one_day():
    quarters = {TimeWindow(SIX_HOURS, T_00_00 + q * SIX_HOURS): (FakeTable(f"q{q}"),) for q in range(4)}
    next_day_01_00 = T_00_00 + DAY + HOUR + 1                 # day ends 23:59:59.999, grace 1 h

    job = POLICY.pick(version(quarters, next_day_01_00))

    assert (job.kind, job.output_window, names(job)) == (JobKind.MOVE_UP, TimeWindow(DAY, T_00_00),
                                                         ["q0", "q1", "q2", "q3"])


BIG = FakeTable("big-06-12", size_bytes=100_000)


def test_p3_late_files_below_10_percent_of_the_big_file_wait():
    late = {W_06_12: (BIG,), hour(10): (FakeTable("late1", 4_000), FakeTable("late2", 5_000))}   # 9%

    assert POLICY.pick(version(late, T_13_00)) is None


def test_p3_late_files_reaching_10_percent_are_merged_into_the_big_window():
    late = {W_06_12: (BIG,), hour(10): (FakeTable("late1", 4_000), FakeTable("late2", 6_000))}   # 10%

    job = POLICY.pick(version(late, T_13_00))

    assert (job.kind, job.output_window, names(job)) == (JobKind.LATE_MERGE, W_06_12,
                                                         ["big-06-12", "late1", "late2"])


def test_p3_four_late_files_in_one_hour_are_not_size_tiered_on_their_own():
    tiny = tuple(FakeTable(f"t{i}", 100) for i in range(4))   # 4 files, but they belong to the 6 h file

    assert POLICY.pick(version({W_06_12: (BIG,), hour(10): tiny}, T_13_00)) is None


def test_p3_a_delete_piece_inside_the_big_window_counts_as_extra():
    piece = FakeTable("delete-piece", 10_000)

    job = POLICY.pick(version({W_06_12: (BIG, piece)}, T_13_00))

    assert (job.kind, names(job)) == (JobKind.LATE_MERGE, ["big-06-12", "delete-piece"])
