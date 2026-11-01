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
