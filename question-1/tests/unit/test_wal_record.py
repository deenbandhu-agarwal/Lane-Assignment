"""WAL record encode / scan (seams 3-6).

Golden bytes come from the walkthrough example (q1-example/make_example.py, a separate encoder),
not from this code: step1 wal/000001.log and step3a wal/000002.log.
"""

from tsdb.model import Point, Tombstone
from tsdb.wal.record import DecodedRecord, encode_delete, encode_put, frame, scan

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
