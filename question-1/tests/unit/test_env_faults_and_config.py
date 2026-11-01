"""EnvFaults (crash harness switch) and EngineConfig.from_env."""

from pathlib import Path

import pytest

from tsdb.config import EngineConfig
from tsdb.faults import CrashPoint, EnvFaults, NoFaults


def test_env_faults_kills_on_the_nth_hit_of_its_own_point_only():
    kills = []
    faults = EnvFaults("manifest_update", after=2, kill=lambda: kills.append("killed"))

    faults.hit(CrashPoint.WAL_APPEND)              # other point: ignored
    faults.hit(CrashPoint.MANIFEST_UPDATE)         # 1st hit: not yet
    assert kills == []
    faults.hit(CrashPoint.MANIFEST_UPDATE)         # 2nd hit: die here
    assert kills == ["killed"]


def test_from_env_without_tsdb_crash_at_injects_nothing(monkeypatch):
    monkeypatch.delenv("TSDB_CRASH_AT", raising=False)
    assert isinstance(EnvFaults.from_env(), NoFaults)


def test_from_env_reads_the_point_and_the_count(monkeypatch):
    kills = []
    monkeypatch.setenv("TSDB_CRASH_AT", "sstable_write")
    monkeypatch.setenv("TSDB_CRASH_AFTER", "3")
    faults = EnvFaults.from_env(kill=lambda: kills.append(1))
    for _ in range(3):
        faults.hit(CrashPoint.SSTABLE_WRITE)
    assert kills == [1]


def test_from_env_rejects_an_unknown_crash_point(monkeypatch):
    monkeypatch.setenv("TSDB_CRASH_AT", "wal_apend")
    with pytest.raises(ValueError, match="wal_append"):     # message lists the valid names
        EnvFaults.from_env()


def test_config_from_env_reads_tsdb_variables_and_keeps_defaults_for_the_rest(monkeypatch):
    monkeypatch.setenv("TSDB_DATA_DIR", "/tmp/x")
    monkeypatch.setenv("TSDB_WAL_COUNT", "2")
    monkeypatch.setenv("TSDB_MEMTABLE_MAX_ENTRIES", "500")
    monkeypatch.setenv("TSDB_WINDOW_STEPS_MS", "60000,120000")

    config = EngineConfig.from_env()

    assert (config.data_dir, config.wal_count, config.memtable_max_entries, config.window_steps_ms) == (
        Path("/tmp/x"), 2, 500, (60_000, 120_000))
    assert config.window_merge_threshold == 4


def test_config_from_env_rejects_a_bad_number(monkeypatch):
    monkeypatch.setenv("TSDB_WAL_COUNT", "two")
    with pytest.raises(ValueError, match="TSDB_WAL_COUNT"):
        EngineConfig.from_env()
