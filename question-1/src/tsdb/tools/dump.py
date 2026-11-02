"""`tsdb-dump <path>... [--hex]`: print an SSTable, WAL segment, series.log or MANIFEST as text.
A directory dumps every file inside. Used for debugging and for the on-disk format demo.

Decoding uses the engine's own code (sstable.reader / format, wal.record, the MANIFEST checksum
rule), so this tool can never disagree with what the engine reads. Exit code 1 if any file is
corrupt (a cut WAL tail is NOT corruption: it is the normal result of a crash mid-append).
"""

from __future__ import annotations

import datetime
import json
import struct
import sys
import zlib
from pathlib import Path

from tsdb.errors import CorruptFileError
from tsdb.model import Point, SeriesKey, TimeWindow
from tsdb.sstable.bloom import BloomFilterFactory
from tsdb.sstable.format import FOOTER_SIZE, HEADER, Footer
from tsdb.sstable.reader import SSTableReader
from tsdb.storage.fileio import OsFileOps
from tsdb.wal.record import scan, scan_frames

_ID = struct.Struct("<I")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    show_hex = "--hex" in args
    paths = [Path(a) for a in args if a != "--hex"]
    if not paths:
        print(__doc__)
        return 2
    ok = True
    for path in paths:
        for file in sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]:
            ok &= _dump(file, show_hex)
    return 0 if ok else 1


def _dump(path: Path, show_hex: bool) -> bool:
    kind = (_sstable if path.suffix == ".sst" else _series_log if path.name == "series.log"
            else _wal if path.suffix == ".log" else _manifest if path.name == "MANIFEST" else None)
    if kind is None:
        return True
    try:
        kind(path, show_hex)
        return True
    except CorruptFileError as e:
        print(f"  CORRUPT: {e}")
        return False
    finally:
        print()


# ------------------------------------------------------------------------------- SSTable
def _sstable(path: Path, show_hex: bool) -> None:
    data = path.read_bytes()
    window = TimeWindow(int(path.parent.parent.name), int(path.parent.name))
    print(f"SSTABLE {path}  ({len(data)} bytes)  window {_duration(window.size_ms)} starting {_time(window.start_ms)}")
    magic, version, _ = HEADER.unpack_from(data)
    print(f"\n[HEADER] bytes 0-{HEADER.size - 1}\n  magic={magic.decode(errors='replace')} version={version}")
    _hex(data[:HEADER.size], 0, show_hex)

    reader = SSTableReader(path, window, OsFileOps(), BloomFilterFactory())
    reader.open()                                       # checks magic + every tail checksum
    footer = Footer.unpack(data[-FOOTER_SIZE:])
    start = len(data) - FOOTER_SIZE
    print(f"\n[FOOTER] bytes {start}-{len(data) - 1}  (read FIRST)  checksum OK")
    for name in ("tombstones", "index", "bloom"):
        print(f"  {name:<10} at byte {getattr(footer, name + '_offset')}, {getattr(footer, name + '_length')} bytes")
    print(f"  time   min {_time(footer.min_ts)}\n         max {_time(footer.max_ts)}")
    print(f"  series min {footer.min_series_id}  max {footer.max_series_id}   points {footer.point_count}")
    _hex(data[start:], start, show_hex)

    print(f"\n[TOMBSTONES] bytes {footer.tombstones_offset}-{footer.tombstones_offset + footer.tombstones_length - 1}  checksum OK")
    for t in reader.all_tombstones() or [None]:
        print("  (none)" if t is None else
              f"  DELETE seq {t.seq}: series {list(t.series_ids)}  from {_time(t.from_ts)}  to {_time(t.to_ts)}")

    print(f"\n[SPARSE INDEX] bytes {footer.index_offset}-{footer.index_offset + footer.index_length - 1}  checksum OK")
    for i, e in enumerate(reader.index):
        print(f"  block {i}: first key (series {e.first_series_id}, {_time(e.first_timestamp)})"
              f"  ->  byte {e.offset}, {e.length} bytes")

    bloom = data[footer.bloom_offset:footer.bloom_offset + footer.bloom_length]
    m_bits, k = struct.unpack_from("<IB", bloom)
    ones = sum(bin(b).count("1") for b in bloom[5:-4])
    print(f"\n[BLOOM] bytes {footer.bloom_offset}-{footer.bloom_offset + footer.bloom_length - 1}  checksum OK")
    print(f"  m={m_bits} bits  k={k} hashes  bits set={ones}/{m_bits}")

    for i, entry in enumerate(reader.index):
        points = reader.read_block(entry)               # checks the block checksum
        print(f"\n[DATA BLOCK {i}] bytes {entry.offset}-{entry.offset + entry.length - 1}"
              f"  {len(points)} point(s)  checksum OK")
        print(f"  {'series':>6}  {'time':<39}  {'seq':>4}  value")
        for p in points:
            print(_point_row(p))
        _hex(data[entry.offset:entry.offset + entry.length], entry.offset, show_hex)


def _point_row(p: Point) -> str:
    return f"  {p.series_id:>6}  {_time(p.timestamp)}  {p.seq:>4}  {p.value}"


# ------------------------------------------------------------------------------- WAL / series.log
def _wal(path: Path, show_hex: bool) -> None:
    data = path.read_bytes()
    print(f"WAL {path}  ({len(data)} bytes)")
    result = scan(data)
    if not data:
        print("  (empty)")
    for r in result.records:
        e = r.entry
        if isinstance(e, Point):
            print(f"  byte {r.offset:5d}: PUT    seq {e.seq}  series {e.series_id}  {_time(e.timestamp)}  value {e.value}")
        else:
            print(f"  byte {r.offset:5d}: DELETE seq {e.seq}  series {list(e.series_ids)}"
                  f"  from {_time(e.from_ts)}  to {_time(e.to_ts)}")
    _cut_tail(result.valid_length, len(data), result.stopped_reason)
    _hex(data, 0, show_hex)


def _series_log(path: Path, show_hex: bool) -> None:
    data = path.read_bytes()
    print(f"SERIES LOG {path}  ({len(data)} bytes)")
    frames, valid, reason = scan_frames(data)
    for offset, payload in frames:
        (series_id,) = _ID.unpack_from(payload)
        metric, tags = json.loads(payload[_ID.size:])
        key = SeriesKey(metric, tuple(tuple(t) for t in tags))
        print(f"  byte {offset:5d}: series {series_id} = {key.canonical()}")
    _cut_tail(valid, len(data), reason)
    _hex(data, 0, show_hex)


def _cut_tail(valid: int, size: int, reason: str | None) -> None:
    if reason:
        print(f"  byte {valid:5d}: {reason.upper()} ({size - valid} bytes) -> replay stops here;"
              " the engine truncates it at startup")


# ------------------------------------------------------------------------------- MANIFEST
def _manifest(path: Path, show_hex: bool) -> None:
    text = path.read_text(errors="replace")
    body, sep, crc_line = text.rpartition("\ncrc32 ")
    ok = sep and crc_line.strip() == f"{zlib.crc32(body.encode()):08x}"
    print(f"MANIFEST {path}  crc32 {'OK' if ok else 'BAD'}")
    if not ok:
        raise CorruptFileError("MANIFEST checksum mismatch")
    state = json.loads(body)
    print(json.dumps(state, indent=2))
    for size, start, names in _windows(state):
        print(f"  window {_duration(size)} starting {_time(start)}: {', '.join(names)}")


def _windows(state: dict):
    for w in state.get("windows", []):
        yield w["size_ms"], w["start_ms"], w["files"]


# ------------------------------------------------------------------------------- helpers
def _time(ms: int) -> str:
    try:
        text = datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    except (OverflowError, OSError, ValueError):
        text = "out of range"
    return f"{text} ({ms})"


def _duration(ms: int) -> str:
    for unit, size in (("d", 86_400_000), ("h", 3_600_000), ("min", 60_000), ("s", 1_000)):
        if ms % size == 0:
            return f"{ms // size} {unit}"
    return f"{ms} ms"


def _hex(data: bytes, base: int, show: bool) -> None:
    if show:
        for i in range(0, len(data), 16):
            print(f"      {base + i:6d}  " + " ".join(f"{b:02x}" for b in data[i:i + 16]))


if __name__ == "__main__":
    raise SystemExit(main())
