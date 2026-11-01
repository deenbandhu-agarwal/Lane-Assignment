"""SSTable write / read through SSTableFactory with real files (seams 1-6).

Golden bytes come from the walkthrough example (q1-example/make_example.py, separate code):
step2 sst/1m/10.00/000001.sst. Our footer is 74 bytes (adds a version field); the example's is
72, so everything BEFORE the footer must match byte for byte.
"""

from pathlib import Path

import pytest

from tsdb.faults import NoFaults
from tsdb.model import Point, TimeWindow
from tsdb.sstable.bloom import BloomFilterFactory
from tsdb.sstable.factory import SSTableFactory
from tsdb.storage.fileio import OsFileOps

MINUTE = 60_000
T_10_00 = 1_730_368_800_000
WINDOW_10_00 = TimeWindow(MINUTE, T_10_00)
TWO_ENTRIES = 2 * 28                     # example: a block closes after 2 entries


def factory(tmp_path: Path, block_target_bytes: int = TWO_ENTRIES) -> SSTableFactory:
    return SSTableFactory(lambda w, n: tmp_path / f"{n:06d}.sst", OsFileOps(), NoFaults(),
                          BloomFilterFactory(), block_target_bytes, filter_fp_rate=0.01)


def write(tables: SSTableFactory, window, file_no, points=(), tombstones=()) -> Path:
    writer = tables.new_writer(window, file_no)
    for t in tombstones:
        writer.add_tombstone(t)
    for p in points:
        writer.add(p)
    return tables.publish(writer.finish(), window, file_no)


EXAMPLE_000001_WITHOUT_FOOTER = bytes.fromhex(
    "54535354010000000200000001000000008504e29201000001000000000000009a999999"
    "99193e4002000000008504e29201000002000000000000000000000000003c40b5e4b985"
    "0100000003000000008504e292010000030000000000000000000000004040408a63a6da"
    "000000001cdf44210200000001000000008504e292010000080000000000000040000000"
    "03000000008504e2920100004800000000000000240000005cb9a730200000000772d5cc"
    "b7bc6be6ae")

STEP2_POINTS = [Point(1, T_10_00, 1, 30.1), Point(2, T_10_00, 2, 28.0), Point(3, T_10_00, 3, 32.5)]


def test_the_example_file_is_written_byte_for_byte_up_to_the_footer(tmp_path):
    path = write(factory(tmp_path), WINDOW_10_00, 1, STEP2_POINTS)

    data = path.read_bytes()
    assert path.name == "000001.sst"
    assert data[:-74] == EXAMPLE_000001_WITHOUT_FOOTER
    assert len(data) == len(EXAMPLE_000001_WITHOUT_FOOTER) + 74
    assert data[-4:] == b"TSST"
