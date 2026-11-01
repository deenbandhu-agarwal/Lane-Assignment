"""tsdb-dump: every file kind of a real data folder printed as text (CLI seam: main(argv) + stdout)."""

import pytest

from tsdb.bootstrap import build_database
from tsdb.config import EngineConfig
from tsdb.model import SeriesKey
from tsdb.tools.dump import main

T = 1_730_368_800_000            # 2024-10-31 10:00:00 UTC
DELHI = SeriesKey.of("temperature", {"city": "Delhi"})
MUMBAI = SeriesKey.of("temperature", {"city": "Mumbai"})


@pytest.fixture
def data(tmp_path):
    """One table (2 points + a delete piece), then a WAL with one more point. Ids start at 1."""
    db = build_database(EngineConfig(data_dir=tmp_path))
    db.write([(DELHI, T, 30.5), (MUMBAI, T, 28.0)])
    db.delete("temperature", "city=Mumbai", T, T + 1000)
    db.run_maintenance_until_idle()
    db.write([(DELHI, T + 60_000, 31.0)])
    db.close()
    return tmp_path / "shard-0"


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    return code, capsys.readouterr().out


def test_sstable_shows_footer_index_tombstones_and_points(data, capsys):
    (table,) = list(data.rglob("*.sst"))
    code, out = run(capsys, table)

    assert code == 0
    assert "SSTABLE" in out and "window 1 h starting 2024-10-31 10:00:00" in out
    assert "[FOOTER]" in out and "checksum OK" in out
    assert "DELETE seq 3: series [2]  from 2024-10-31 10:00:00.000 (1730368800000)" in out
    assert "1  2024-10-31 10:00:00.000 (1730368800000)     1  30.5" in out


def test_wal_shows_records_and_where_a_cut_tail_stops_replay(data, capsys):
    (segment,) = [p for p in data.rglob("*.log") if p.name != "series.log" and p.stat().st_size]
    with open(segment, "ab") as f:
        f.write(b"\x40\x00\x00\x00\x01\x02")                    # half a frame: a crash mid-append
    code, out = run(capsys, segment)

    assert "PUT    seq 4  series 1  2024-10-31 10:01:00.000 (1730368860000)  value 31.0" in out
    assert "replay stops here" in out
    assert code == 0                                           # a cut tail is normal after a crash


def test_series_log_and_manifest(data, capsys):
    _, out = run(capsys, data / "series.log")
    assert "series 1 = temperature{city=Delhi}" in out and "series 2 = temperature{city=Mumbai}" in out

    _, out = run(capsys, data / "MANIFEST")
    assert '"wal_count": 1' in out and "crc32 OK" in out


def test_a_folder_dumps_every_file_and_a_corrupt_table_is_reported_not_crashed(data, capsys):
    (table,) = list(data.rglob("*.sst"))
    raw = bytearray(table.read_bytes())
    raw[-1] ^= 0xFF                                            # break the footer magic
    table.write_bytes(bytes(raw))

    code, out = run(capsys, data)

    assert "SERIES LOG" in out and "MANIFEST" in out and "WAL" in out
    assert "CORRUPT" in out
    assert code == 1


def test_hex_prints_raw_bytes(data, capsys):
    _, out = run(capsys, data / "series.log", "--hex")
    assert "      0  " in out                                  # offset column of the hex dump
