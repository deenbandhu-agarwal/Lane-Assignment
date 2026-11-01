"""Series catalog with real files (seams C1-C2)."""

import threading

from tsdb.catalog.series_catalog import SeriesCatalog
from tsdb.model import SeriesKey
from tsdb.storage.fileio import OsFileOps

DELHI = SeriesKey.of("temperature", {"city": "Delhi", "sensor": "roof"})
MUMBAI = SeriesKey.of("temperature", {"city": "Mumbai", "sensor": "roof"})
ODD = SeriesKey.of("m", {"a": "1,b=2", "ü": "x\"y"})


def catalog(tmp_path, told=None):
    c = SeriesCatalog(tmp_path / "series.log", OsFileOps(),
                      on_new_series=(lambda i, k: told.append((i, k))) if told is not None else (lambda i, k: None))
    c.load()
    return c


def test_a_new_series_gets_the_next_id_and_the_same_key_gets_the_same_id(tmp_path):
    told = []
    c = catalog(tmp_path, told)

    assert c.get_or_create(DELHI) == (1, True)
    assert c.get_or_create(MUMBAI) == (2, True)
    assert c.get_or_create(DELHI) == (1, False)
    assert c.key_of(2) == MUMBAI
    assert len(c) == 2
    assert told == [(1, DELHI), (2, MUMBAI)]                  # the index hears about each new series once


def test_ids_survive_a_restart_and_the_index_is_rebuilt(tmp_path):
    c = catalog(tmp_path)
    c.get_or_create(DELHI), c.get_or_create(MUMBAI), c.get_or_create(ODD)
    c.sync()

    told = []
    again = catalog(tmp_path, told)                            # new process

    assert again.get_or_create(ODD) == (3, False)
    assert again.key_of(1) == DELHI
    assert told == [(1, DELHI), (2, MUMBAI), (3, ODD)]
    assert again.get_or_create(SeriesKey.of("cpu", {})) == (4, True)


def test_a_record_cut_by_a_crash_is_dropped_and_the_file_is_repaired_for_new_records(tmp_path):
    c = catalog(tmp_path)
    c.get_or_create(DELHI), c.get_or_create(MUMBAI)
    c.sync()
    log = tmp_path / "series.log"
    log.write_bytes(log.read_bytes()[:-5])                      # MUMBAI's record cut

    again = catalog(tmp_path)
    assert again.get_or_create(MUMBAI) == (2, True)             # id 2 is free again
    again.sync()

    third = catalog(tmp_path)                                   # the cut bytes must not hide the new record
    assert (third.key_of(1), third.key_of(2)) == (DELHI, MUMBAI)
