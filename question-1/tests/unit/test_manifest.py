"""MANIFEST store with real files (seams 1-3)."""

import pytest

from tsdb.errors import CorruptFileError
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
    version=4, next_file_no=8, last_flushed_seq=10, wal_segment=3,
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


class StopAt:
    """Fake fault injector: raises at one crash point, like the process dying there."""

    def __init__(self, point: str) -> None:
        self.point = point

    def hit(self, point: str) -> None:
        if point == self.point:
            raise SystemExit(f"crash at {point}")


STATE_V5 = ManifestState(version=5, next_file_no=9, last_flushed_seq=14, wal_segment=4,
                         newest_data_ts=1_730_372_520_000,
                         windows=((TimeWindow(SIX_HOURS, T_06_00), ("000006.sst", "000008.sst")),))


def test_a_crash_between_writing_the_tmp_file_and_the_rename_keeps_the_old_state(tmp_path):
    store(tmp_path).commit(STATE_V4)

    with pytest.raises(SystemExit):
        store(tmp_path, StopAt("manifest_update")).commit(STATE_V5)

    assert (tmp_path / "MANIFEST.tmp").exists()            # the new state was written ...
    assert store(tmp_path).load() == STATE_V4              # ... but never became visible


def test_the_next_commit_after_a_crash_works_and_replaces_the_leftover_tmp(tmp_path):
    store(tmp_path).commit(STATE_V4)
    with pytest.raises(SystemExit):
        store(tmp_path, StopAt("manifest_update")).commit(STATE_V5)

    store(tmp_path).commit(STATE_V5)

    assert store(tmp_path).load() == STATE_V5
    assert not (tmp_path / "MANIFEST.tmp").exists()


@pytest.mark.parametrize("where", ["body", "checksum line"])
def test_one_damaged_byte_is_refused(tmp_path, where):
    store(tmp_path).commit(STATE_V4)
    path = tmp_path / "MANIFEST"
    data = bytearray(path.read_bytes())
    at = data.index(b'"next_file_no": 8') + len(b'"next_file_no": ') if where == "body" else len(data) - 3
    data[at] = ord("9") if data[at] != ord("9") else ord("1")        # 8 -> 9 still valid JSON
    path.write_bytes(bytes(data))

    with pytest.raises(CorruptFileError):
        store(tmp_path).load()


def test_a_manifest_cut_short_is_refused(tmp_path):
    store(tmp_path).commit(STATE_V4)
    path = tmp_path / "MANIFEST"
    path.write_bytes(path.read_bytes()[:40])

    with pytest.raises(CorruptFileError):
        store(tmp_path).load()
