"""MANIFEST store (implements ports.ManifestPort): the single source of truth for live files.

Replaced as a whole with atomic rename. The rename is THE moment a flush or a compaction becomes
visible after a crash. Contains a checksum so a damaged file is detected.

Format (readable with `cat`):   <JSON body>\ncrc32 <8 hex digits of crc32(JSON body)>\n
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

from tsdb.errors import CorruptFileError
from tsdb.faults import CrashPoint
from tsdb.model import ManifestState, TimeWindow
from tsdb.ports import FaultInjector, FileOps


class ManifestStore:
    def __init__(self, path: Path, files: FileOps, faults: FaultInjector) -> None:
        self._path = path
        self._files = files
        self._faults = faults

    def load(self) -> ManifestState | None:
        """None for a fresh directory. Raises CorruptFileError on a bad checksum."""
        if not self._path.exists():
            return None
        text = self._files.read_all(self._path).decode(errors="replace")
        body, sep, crc_line = text.rpartition("\ncrc32 ")
        if not sep or crc_line.strip() != f"{zlib.crc32(body.encode()):08x}":
            raise CorruptFileError(f"MANIFEST checksum mismatch in {self._path}")
        return _from_json(json.loads(body))

    def commit(self, state: ManifestState) -> None:
        """Atomic replace; faults.hit(MANIFEST_UPDATE) between write and rename."""
        body = json.dumps(_to_json(state), indent=2)
        tmp = self._path.with_name(self._path.name + ".tmp")
        self._files.remove(tmp)                       # leftover from an earlier crash
        fd = self._files.open_append(tmp)
        try:
            self._files.append(fd, f"{body}\ncrc32 {zlib.crc32(body.encode()):08x}\n".encode())
            self._files.fsync(fd)
        finally:
            self._files.close(fd)
        self._faults.hit(CrashPoint.MANIFEST_UPDATE)
        self._files.publish_tmp(tmp, self._path)


def _to_json(state: ManifestState) -> dict:
    return {
        "version": state.version,
        "next_file_no": state.next_file_no,
        "last_flushed_seq": state.last_flushed_seq,
        "wal_segment": state.wal_segment,
        "newest_data_ts": state.newest_data_ts,
        "windows": [{"size_ms": w.size_ms, "start_ms": w.start_ms, "files": list(files)}
                    for w, files in state.windows],
    }


def _from_json(d: dict) -> ManifestState:
    return ManifestState(
        version=d["version"], next_file_no=d["next_file_no"], last_flushed_seq=d["last_flushed_seq"],
        wal_segment=d["wal_segment"], newest_data_ts=d["newest_data_ts"],
        windows=tuple((TimeWindow(w["size_ms"], w["start_ms"]), tuple(w["files"])) for w in d["windows"]))
