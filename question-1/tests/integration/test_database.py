"""Database built by bootstrap on a real folder, real threads (seams S1-S3, S5)."""

import pytest

from tsdb.bootstrap import build_database
from tsdb.config import EngineConfig
from tsdb.model import Aggregation, SeriesKey

T = 1_730_368_800_000                       # 2024-10-31 10:00:00 UTC
MINUTE = 60_000
DELHI = SeriesKey.of("temperature", {"city": "Delhi", "sensor": "roof"})
MUMBAI = SeriesKey.of("temperature", {"city": "Mumbai", "sensor": "roof"})


def answer(result):
    """{series key: [(ts, value), ...]} — easy to compare with a literal."""
    return {s.key: s.points for s in result.series}


@pytest.fixture
def db(tmp_path):
    d = build_database(EngineConfig(data_dir=tmp_path))
    yield d
    d.close()


def test_s1_written_points_come_back_raw_and_aggregated(db):
    assert db.write([(DELHI, T, 30.0), (DELHI, T + MINUTE, 32.0), (MUMBAI, T, 28.0)]) == 3

    raw = db.query("temperature", "city=Delhi", T, T + MINUTE, None, None)
    avg = db.query("temperature", None, T, T + MINUTE, Aggregation.AVG, 5 * MINUTE)

    assert answer(raw) == {DELHI: [(T, 30.0), (T + MINUTE, 32.0)]}
    assert answer(avg) == {DELHI: [(T, 31.0)], MUMBAI: [(T, 28.0)]}


def test_s1_data_flushed_by_the_background_thread_is_still_read(tmp_path):
    """A memtable of 2 entries: the flush thread writes tables while we keep writing."""
    d = build_database(EngineConfig(data_dir=tmp_path, memtable_max_entries=2))
    try:
        for i in range(10):
            d.write([(DELHI, T + i * MINUTE, float(i))])
        d.run_maintenance_until_idle()

        result = d.query("temperature", "city=Delhi", T, T + 9 * MINUTE, None, None)

        assert answer(result) == {DELHI: [(T + i * MINUTE, float(i)) for i in range(10)]}
        assert result.stats["tables_in_range"] >= 1
    finally:
        d.close()


def test_s2_after_close_and_reopen_every_answer_is_the_same(tmp_path):
    """Half the data in tables (flushed), half only in the WAL; a series created after the flush."""
    first = build_database(EngineConfig(data_dir=tmp_path))
    first.write([(DELHI, T, 30.0), (MUMBAI, T, 28.0)])
    first.run_maintenance_until_idle()
    first.write([(DELHI, T + MINUTE, 32.0), (DELHI, T, 31.0)])          # overwrite of T, WAL only
    pune = SeriesKey.of("temperature", {"city": "Pune", "sensor": "roof"})
    first.write([(pune, T, 25.0)])
    first.close()

    again = build_database(EngineConfig(data_dir=tmp_path))
    try:
        assert answer(again.query("temperature", None, T, T + MINUTE, None, None)) == {
            DELHI: [(T, 31.0), (T + MINUTE, 32.0)], MUMBAI: [(T, 28.0)], pune: [(T, 25.0)]}
        again.write([(DELHI, T, 35.0)])              # wins only if seq continues above the old ones
        assert answer(again.query("temperature", "city=Delhi", T, T + MINUTE, None, None)) == {
            DELHI: [(T, 35.0), (T + MINUTE, 32.0)]}
    finally:
        again.close()


def test_s3_delete_by_filter_hides_old_points_in_range_and_a_later_write_is_visible(tmp_path):
    d = build_database(EngineConfig(data_dir=tmp_path))
    try:
        d.write([(MUMBAI, T, 28.0), (MUMBAI, T + MINUTE, 29.0), (MUMBAI, T + 2 * MINUTE, 30.0),
                 (DELHI, T, 31.0)])
        d.run_maintenance_until_idle()                               # the old points are in a table

        assert d.delete("temperature", "city=Mumbai", T, T + MINUTE) == 1
        d.write([(MUMBAI, T, 40.0)])                                 # after the delete: visible

        everything = d.query("temperature", None, T, T + 2 * MINUTE, None, None)
        assert answer(everything) == {MUMBAI: [(T, 40.0), (T + 2 * MINUTE, 30.0)], DELHI: [(T, 31.0)]}
        d.run_maintenance_until_idle()                               # tombstone flushed + compacted
        assert answer(d.query("temperature", None, T, T + 2 * MINUTE, None, None)) == answer(everything)
        assert d.list_series("temperature", "city=Mumbai").series == [MUMBAI]   # still listed (#41)
        assert d.delete("temperature", "city=Chennai", T, T) == 0
    finally:
        d.close()
