"""SSTable write / read through SSTableFactory with real files (seams 1-6).

Golden bytes come from the walkthrough example (q1-example/make_example.py, separate code):
step2 sst/1m/10.00/000001.sst. Our footer is 74 bytes (adds a version field); the example's is
72, so everything BEFORE the footer must match byte for byte.
"""

from pathlib import Path

import pytest

from tsdb.errors import CorruptFileError
from tsdb.faults import NoFaults
from tsdb.model import Point, TimeWindow, Tombstone
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


SECOND = 1_000
# 4 series x 10 seconds = 40 points; with 2 entries per block that is 20 blocks
MANY_POINTS = [Point(sid, T_10_00 + s * SECOND, seq=sid * 100 + s, value=sid + s / 10)
               for sid in (1, 2, 5, 9) for s in range(10)]
DELETE_2_AND_9 = Tombstone(seq=500, series_ids=(2, 9), from_ts=T_10_00 + 3 * SECOND, to_ts=T_10_00 + 5 * SECOND)
DELETE_7_ONLY = Tombstone(seq=501, series_ids=(7,), from_ts=T_10_00 + 50 * SECOND, to_ts=T_10_00 + 59 * SECOND)


def test_points_and_tombstones_come_back_exactly_as_written(tmp_path):
    tables = factory(tmp_path)
    path = write(tables, WINDOW_10_00, 2, MANY_POINTS, [DELETE_2_AND_9, DELETE_7_ONLY])

    reader = tables.open_reader(path, WINDOW_10_00)

    assert list(reader.iter_all()) == MANY_POINTS
    assert reader.all_tombstones() == [DELETE_2_AND_9, DELETE_7_ONLY]
    assert reader.tombstones_for(2) == [DELETE_2_AND_9]
    assert reader.tombstones_for(7) == [DELETE_7_ONLY]
    assert reader.tombstones_for(1) == []
    assert (reader.min_ts, reader.max_ts) == (T_10_00, T_10_00 + 59 * SECOND)   # tombstones count too
    assert reader.size_bytes == path.stat().st_size
    reader.close()


def damage(path: Path, at: int) -> None:
    data = bytearray(path.read_bytes())
    data[at] ^= 0x01
    path.write_bytes(bytes(data))


@pytest.fixture
def example_file(tmp_path):
    tables = factory(tmp_path)
    return tables, write(tables, WINDOW_10_00, 1, STEP2_POINTS)


def test_a_wrong_magic_at_the_end_is_refused(example_file):
    tables, path = example_file
    damage(path, path.stat().st_size - 1)

    with pytest.raises(CorruptFileError, match="magic"):
        tables.open_reader(path, WINDOW_10_00)


def test_one_flipped_bit_in_the_footer_is_refused(example_file):
    tables, path = example_file
    damage(path, path.stat().st_size - 74 + 3)          # inside the index offset

    with pytest.raises(CorruptFileError, match="checksum"):
        tables.open_reader(path, WINDOW_10_00)


def test_one_flipped_bit_in_the_tail_is_refused_at_open(example_file):
    tables, path = example_file
    damage(path, 172 + 6)                                # a Bloom bits byte (Bloom block at 172)

    with pytest.raises(CorruptFileError, match="checksum"):
        tables.open_reader(path, WINDOW_10_00)


def test_one_flipped_bit_in_a_data_block_is_refused_when_that_block_is_read(example_file):
    tables, path = example_file
    damage(path, 8 + 4 + 27)                             # value of the first point (block 0 at 8)
    reader = tables.open_reader(path, WINDOW_10_00)      # tail is fine, so open works

    with pytest.raises(CorruptFileError, match="checksum"):
        list(reader.iter_all())


def test_a_file_cut_short_is_refused(example_file):
    tables, path = example_file
    path.write_bytes(path.read_bytes()[:100])

    with pytest.raises(CorruptFileError):
        tables.open_reader(path, WINDOW_10_00)


def test_a_range_read_returns_exactly_the_points_in_range_and_reads_only_their_blocks(tmp_path):
    tables = factory(tmp_path)
    reader = tables.open_reader(write(tables, WINDOW_10_00, 2, MANY_POINTS), WINDOW_10_00)
    # series 2 sits in blocks 5..9 (2 points per block): s0-1, s2-3, s4-5, s6-7, s8-9
    cursor = reader.cursor()

    got = list(cursor.read_series(2, T_10_00 + 3 * SECOND, T_10_00 + 6 * SECOND))

    assert got == [p for p in MANY_POINTS if p.series_id == 2 and 3 <= (p.timestamp - T_10_00) // SECOND <= 6]
    assert cursor.blocks_read == 3                       # s2-3, s4-5, s6-7 out of 20 blocks


def test_a_series_outside_the_files_data_gives_nothing(tmp_path):
    tables = factory(tmp_path)
    reader = tables.open_reader(write(tables, WINDOW_10_00, 2, MANY_POINTS), WINDOW_10_00)

    assert list(reader.cursor().read_series(1, T_10_00 + 30 * SECOND, T_10_00 + 40 * SECOND)) == []
    assert list(reader.cursor().read_series(10, T_10_00, T_10_00 + 59 * SECOND)) == []


def test_the_next_series_in_the_same_block_does_not_read_the_block_again(example_file):
    tables, path = example_file                          # block 0 = series 1, 2 ; block 1 = series 3
    cursor = tables.open_reader(path, WINDOW_10_00).cursor()
    whole_minute = (T_10_00, T_10_00 + MINUTE - 1)

    assert list(cursor.read_series(1, *whole_minute)) == STEP2_POINTS[0:1]
    assert list(cursor.read_series(2, *whole_minute)) == STEP2_POINTS[1:2]
    assert cursor.blocks_read == 1
    assert list(cursor.read_series(3, *whole_minute)) == STEP2_POINTS[2:3]
    assert cursor.blocks_read == 2


def test_may_contain_skips_by_series_range_time_range_and_bloom_but_never_hides_a_tombstone(tmp_path):
    tables = factory(tmp_path)
    reader = tables.open_reader(write(tables, WINDOW_10_00, 2, MANY_POINTS, [DELETE_2_AND_9, DELETE_7_ONLY]),
                                WINDOW_10_00)
    minute = (T_10_00, T_10_00 + MINUTE - 1)

    assert reader.may_contain(1, *minute)                                  # has points
    assert reader.may_contain(7, *minute)                                  # only a tombstone here
    assert not reader.may_contain(10, *minute)                             # above max series id 9
    assert not reader.may_contain(1, T_10_00 - MINUTE, T_10_00 - 1)        # before min_ts
    assert not reader.may_contain(1, T_10_00 + MINUTE, T_10_00 + 2 * MINUTE)   # after max_ts
    assert not reader.may_contain(3, *minute)    # inside 1..9 but absent; this filter (5 ids) answers "no" for 3


@pytest.mark.parametrize("bad_second_point, why", [
    (Point(1, T_10_00, seq=9, value=0.0), "same key twice (two versions)"),
    (Point(1, T_10_00 - 1, seq=9, value=0.0), "older time, same series"),
    (Point(0, T_10_00 + SECOND, seq=9, value=0.0), "smaller series id"),
])
def test_the_writer_refuses_points_out_of_key_order(tmp_path, bad_second_point, why):
    writer = factory(tmp_path).new_writer(WINDOW_10_00, 3)
    writer.add(Point(1, T_10_00, seq=1, value=0.0))

    with pytest.raises(ValueError):
        writer.add(bad_second_point)


def test_the_writer_refuses_a_point_or_tombstone_outside_its_window(tmp_path):
    writer = factory(tmp_path).new_writer(WINDOW_10_00, 3)

    with pytest.raises(ValueError):
        writer.add(Point(1, T_10_00 + MINUTE, seq=1, value=0.0))          # 10:01:00.000, next window
    with pytest.raises(ValueError):
        writer.add_tombstone(Tombstone(5, (1,), T_10_00 + 30 * SECOND, T_10_00 + MINUTE))   # not clipped
