"""MANIFEST store with real files (seams 1-3)."""

import pytest

from tsdb.faults import NoFaults
from tsdb.model import ManifestState, TimeWindow
from tsdb.storage.fileio import OsFileOps
from tsdb.storage.manifest import ManifestStore

HOUR = 3_600_000
SIX_HOURS = 6 * HOUR
T_06_00 = 1_730_354_400_000
T_10_00 = 1_730_368_800_000
T_11_00 = 1_730_372_400_000

STATE_V4 = ManifestState(
    version=4, next_file_no=8, last_flushed_seq=10, wal_count=4, wal_segment=3,
    newest_data_ts=1_730_372_460_000,
    windows=(
        (TimeWindow(SIX_HOURS, T_06_00), ("000006.sst",)),
        (TimeWindow(HOUR, T_10_00), ("000005.sst", "000007.sst")),
        (TimeWindow(HOUR, T_11_00), ()),
    ))


def store(tmp_path, faults=None) -> ManifestStore:
    return ManifestStore(tmp_path / "MANIFEST", OsFileOps(), faults or NoFaults())


def test_a_fresh_directory_has_no_manifest(tmp_path):
    assert store(tmp_path).load() is None


def test_a_committed_state_loads_back_unchanged_even_in_a_new_process(tmp_path):
    store(tmp_path).commit(STATE_V4)

    assert store(tmp_path).load() == STATE_V4
