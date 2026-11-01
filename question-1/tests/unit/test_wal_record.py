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
