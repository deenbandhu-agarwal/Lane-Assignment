"""Compaction end to end: a real database, 1/2/4-minute windows, merge at 2 files."""

import random

import pytest

from tests.integration.disk import tables
from tsdb.bootstrap import build_database
from tsdb.config import EngineConfig
from tsdb.model import SeriesKey

T = 1_730_368_800_000                       # divisible by 4 minutes: windows line up with T
MINUTE = 60_000
STEPS = (MINUTE, 2 * MINUTE, 4 * MINUTE)
CITIES = ["Delhi", "Mumbai", "Pune"]


def key(city):
    return SeriesKey.of("temperature", {"city": city})


def read_all(db):
    result = db.query("temperature", None, 0, 2**62, None, None)
    return {(s.key, ts): v for s in result.series for ts, v in s.points}


@pytest.fixture
def config(tmp_path):
    return EngineConfig(data_dir=tmp_path, window_steps_ms=STEPS, window_merge_threshold=2,
                        memtable_max_entries=50)


def test_repeated_compaction_no_loss_no_duplicates(config):
    """Seeded writes, overwrites and deletes; a dict is the oracle; compare after every round."""
    rng, oracle = random.Random(3), {}
    db = build_database(config)
    try:
        for round_no in range(8):
            for _ in range(60):
                ts = T + rng.randrange((round_no + 1) * 2 * MINUTE)   # time moves on, late points too
                city, value = rng.choice(CITIES), round(rng.uniform(0, 50), 2)
                db.write([(key(city), ts, value)])
                oracle[(key(city), ts)] = value
            city = rng.choice(CITIES)
            start = T + rng.randrange((round_no + 1) * 2 * MINUTE)
            db.delete("temperature", f"city={city}", start, start + 20_000)
            for k in [k for k in oracle if k[0] == key(city) and start <= k[1] <= start + 20_000]:
                del oracle[k]
            db.run_maintenance_until_idle()
            assert read_all(db) == oracle, f"round {round_no}"
        assert any(w.size_ms == 4 * MINUTE for w, _ in tables(config.data_dir))   # move-up happened
    finally:
        db.close()


def test_every_table_stays_inside_one_window(config):
    db = build_database(config)
    try:
        for i in range(400):                                   # memtables cross window edges
            db.write([(key(CITIES[i % 3]), T + i * 1_500, float(i))])
        db.write([(key("Delhi"), T + 30_000, -1.0)])           # a late point
        db.run_maintenance_until_idle()
        found = tables(config.data_dir)
        assert found
        for window, table in found:
            if table.max_ts >= table.min_ts:                    # delete-only tables hold no points
                assert window.contains(table.min_ts) and window.contains(table.max_ts), table.name
    finally:
        db.close()


def test_size_tiered_inside_window_only(config):
    """Two flushes into minute 0 and two into minute 1, all still open: each minute merges alone."""
    db = build_database(config.__class__(**{**_fields(config), "memtable_max_entries": 10**6}))
    try:
        for ts in (T, T + 1, T + MINUTE, T + MINUTE + 1):
            db.write([(key("Delhi"), ts, 1.0)])
            db.run_maintenance_until_idle()
        assert sorted((w.size_ms, w.start_ms) for w, _ in tables(config.data_dir)) == [
            (MINUTE, T), (MINUTE, T + MINUTE)]                  # one file each, never mixed
    finally:
        db.close()


def test_move_up_when_all_children_closed(config):
    db = build_database(config)
    try:
        db.write([(key("Delhi"), T + m * MINUTE, float(m)) for m in range(4)])    # minutes 0-3
        db.run_maintenance_until_idle()
        assert 4 * MINUTE not in {w.size_ms for w, _ in tables(config.data_dir)}  # minutes 2-3 still open
        db.write([(key("Delhi"), T + 10 * MINUTE, 10.0)])                         # closes them
        db.run_maintenance_until_idle()
        assert sorted((w.size_ms, w.start_ms) for w, _ in tables(config.data_dir)) == sorted([
            (4 * MINUTE, T), (MINUTE, T + 10 * MINUTE)])
        assert len(read_all(db)) == 5
    finally:
        db.close()


def test_tombstone_dropped_only_by_rule_2(config):
    """Delete over two open windows: each window's merge covers every file holding the series in
    that range -> the tombstone and the data are gone from disk.
    The KEEP case of Rule 2 cannot be reached end to end with this policy: every job takes all
    files nested in its top window (design-qa #51). It is unit-tested in test_rule2.py."""
    db = build_database(config)
    try:
        db.write([(key("Delhi"), T, 1.0)])
        db.run_maintenance_until_idle()
        db.write([(key("Delhi"), T + 1, 2.0), (key("Delhi"), T + MINUTE, 3.0)])
        db.run_maintenance_until_idle()
        db.delete("temperature", "city=Delhi", T, T + MINUTE)        # pieces in minute 0 and minute 1
        db.run_maintenance_until_idle()

        by_window = {(w.size_ms, w.start_ms): t for w, t in tables(config.data_dir)}
        assert read_all(db) == {}
        assert all(t.all_tombstones() == [] for t in by_window.values())
        assert all(t.max_ts < t.min_ts for t in by_window.values())  # no point left on disk
    finally:
        db.close()


def test_late_files_merge_threshold(config):
    """A late 1-point file inside a moved-up 4-minute window waits (< 10% of the big file);
    enough late data (>= 10%) merges into it."""
    db = build_database(config.__class__(**{**_fields(config), "memtable_max_entries": 10**6}))
    try:
        db.write([(key(c), T + i * 100, float(i)) for c in CITIES for i in range(2_400)])   # minutes 0-3
        db.write([(key("Delhi"), T + 10 * MINUTE, 0.0)])
        db.run_maintenance_until_idle()
        db.write([(key("Pune"), T + 30, -1.0)])                       # 1 late point in minute 0
        db.run_maintenance_until_idle()
        assert sorted((w.size_ms, w.start_ms) for w, _ in tables(config.data_dir)) == sorted([
            (MINUTE, T), (4 * MINUTE, T), (MINUTE, T + 10 * MINUTE)])  # waits
        db.write([(key("Mumbai"), T + 50 + i * 100, -2.0) for i in range(1_000)])   # ~14% of the big file
        db.run_maintenance_until_idle()
        assert sorted((w.size_ms, w.start_ms) for w, _ in tables(config.data_dir)) == sorted([
            (4 * MINUTE, T), (MINUTE, T + 10 * MINUTE)])               # merged
        assert len(read_all(db)) == 3 * 2_400 + 1 + 1 + 1_000
    finally:
        db.close()


def _fields(config):
    return {f: getattr(config, f) for f in config.__dataclass_fields__}
