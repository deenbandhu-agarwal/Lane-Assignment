"""Overwrite and delete semantics across every place data can live: memtable, table, compacted
table, after restart."""

import pytest

from tsdb.bootstrap import build_database
from tsdb.config import EngineConfig
from tsdb.model import SeriesKey

T = 1_730_368_800_000
MINUTE = 60_000
DELHI = SeriesKey.of("temperature", {"city": "Delhi"})


def points(db, from_ts=T, to_ts=T + 10 * MINUTE):
    result = db.query("temperature", None, from_ts, to_ts, None, None)
    return {s.key: s.points for s in result.series}


@pytest.fixture
def config(tmp_path):
    return EngineConfig(data_dir=tmp_path, window_steps_ms=(MINUTE, 2 * MINUTE, 4 * MINUTE),
                        window_merge_threshold=2)


def test_duplicate_timestamp_last_write_wins(config):
    db = build_database(config)
    try:
        db.write([(DELHI, T, 1.0)])
        db.run_maintenance_until_idle()                       # 1.0 in a table
        db.write([(DELHI, T, 2.0)])                           # 2.0 in the memtable
        assert points(db) == {DELHI: [(T, 2.0)]}
        db.run_maintenance_until_idle()                       # 2 files in one window -> compacted
        db.write([(DELHI, T, 3.0), (DELHI, T, 4.0)])          # twice in ONE batch: the later one wins
        assert points(db) == {DELHI: [(T, 4.0)]}
        db.run_maintenance_until_idle()
        assert points(db) == {DELHI: [(T, 4.0)]}
    finally:
        db.close()
    again = build_database(config)
    try:
        assert points(again) == {DELHI: [(T, 4.0)]}
    finally:
        again.close()


def test_delete_survives_flush_compaction_restart(config):
    db = build_database(config)
    try:
        db.write([(DELHI, T + i * 1000, float(i)) for i in range(10)])
        db.run_maintenance_until_idle()
        db.delete("temperature", "city=Delhi", T, T + 4_000)
        expected = {DELHI: [(T + i * 1000, float(i)) for i in range(5, 10)]}
        assert points(db) == expected                          # tombstone in memtable
        db.run_maintenance_until_idle()
        assert points(db) == expected                          # tombstone flushed + compacted
    finally:
        db.close()
    again = build_database(config)
    try:
        assert points(again) == expected
        again.run_maintenance_until_idle()
        assert points(again) == expected
    finally:
        again.close()


def test_write_after_delete_is_visible(config):
    db = build_database(config)
    try:
        db.write([(DELHI, T, 1.0)])
        db.run_maintenance_until_idle()
        db.delete("temperature", "city=Delhi", 0, 2**62)       # all time
        db.write([(DELHI, T, 5.0)])
        assert points(db) == {DELHI: [(T, 5.0)]}
        db.run_maintenance_until_idle()
        assert points(db) == {DELHI: [(T, 5.0)]}
    finally:
        db.close()
