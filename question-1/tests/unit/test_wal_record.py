"""WAL record encode / scan (seams 3-6).

Golden bytes come from the walkthrough example (q1-example/make_example.py, a separate encoder),
not from this code: step1 wal/000001.log and step3a wal/000002.log.
"""

from tsdb.model import Point, Tombstone
from tsdb.wal.record import DecodedRecord, ScanResult, encode_delete, encode_put, frame, scan

T_10_00 = 1_730_368_800_000
T_10_01 = 1_730_368_860_000

# PUT seq 1, series 1, 10:00:00, 30.1  ->  length 29 | crc32 | type 1 | seq | sid | ts | value
PUT_SEQ1 = bytes.fromhex(
    "1d000000" "33674b21" "01" "0100000000000000" "01000000" "008504e292010000" "9a99999999193e40")


def test_a_put_encodes_to_the_37_bytes_on_the_example_page_and_scans_back():
    point = Point(series_id=1, timestamp=T_10_00, seq=1, value=30.1)

    data = frame(encode_put(point))

    assert data == PUT_SEQ1
    assert scan(data).records == [DecodedRecord(offset=0, entry=point)]


# DELETE seq 10, series [3], 10:00:00 .. 10:01:00
#   length 33 | crc32 | type 2 | seq | from | to | count 1 | id 3
DELETE_SEQ10 = bytes.fromhex(
    "21000000" "8262f3d9" "02" "0a00000000000000" "008504e292010000" "606f05e292010000"
    "01000000" "03000000")


def test_a_delete_encodes_to_the_41_bytes_on_the_example_page_and_scans_back():
    delete = Tombstone(seq=10, series_ids=(3,), from_ts=T_10_00, to_ts=T_10_01)

    data = frame(encode_delete(delete))

    assert data == DELETE_SEQ10
    assert scan(data).records == [DecodedRecord(offset=0, entry=delete)]


def test_a_delete_over_several_series_keeps_every_id_in_order():
    delete = Tombstone(seq=11, series_ids=(2, 5, 9), from_ts=T_10_00, to_ts=T_10_01)

    payload = encode_delete(delete)

    assert len(payload) == 1 + 8 + 8 + 8 + 4 + 3 * 4
    assert scan(frame(payload)).records[0].entry == delete


# Example step 1 wal/000001.log: 4 PUTs of 37 bytes at offsets 0, 37, 74, 111 (148 bytes)
STEP1_WAL = bytes.fromhex(
    "1d00000033674b2101010000000000000001000000008504e2920100009a99999999193e40"
    "1d000000b1e0da4f01020000000000000002000000008504e2920100000000000000003c40"
    "1d000000d09d18d801030000000000000003000000008504e29201000000000000004040"
    "40"
    "1d0000000cc42b7c01040000000000000001000000606f05e2920100006666666666663e40")


def test_the_whole_example_file_scans_to_four_records_with_a_clean_end():
    result = scan(STEP1_WAL)

    assert [r.offset for r in result.records] == [0, 37, 74, 111]
    assert [r.entry.seq for r in result.records] == [1, 2, 3, 4]
    assert (result.valid_length, result.stopped_reason) == (148, None)


def test_a_record_cut_inside_its_header_is_dropped_and_the_file_is_valid_up_to_it():
    result = scan(STEP1_WAL[:111 + 5])          # crash wrote only 5 of the 8 header bytes

    assert [r.entry.seq for r in result.records] == [1, 2, 3]
    assert (result.valid_length, result.stopped_reason) == (111, "cut record")


def test_a_record_cut_inside_its_payload_is_dropped_and_the_file_is_valid_up_to_it():
    result = scan(STEP1_WAL[:111 + 20])         # header complete, payload cut short

    assert [r.entry.seq for r in result.records] == [1, 2, 3]
    assert (result.valid_length, result.stopped_reason) == (111, "cut record")


def test_an_empty_file_has_no_records_and_a_clean_end():
    assert scan(b"") == ScanResult(records=[], valid_length=0, stopped_reason=None)


def test_one_damaged_byte_in_record_two_stops_the_scan_after_record_one():
    damaged = bytearray(STEP1_WAL)
    damaged[37 + 8 + 25] ^= 0x01               # one bit of record 2's value (payload bytes 21-28)

    result = scan(bytes(damaged))

    assert [r.entry.seq for r in result.records] == [1]
    assert (result.valid_length, result.stopped_reason) == (37, "bad checksum")
