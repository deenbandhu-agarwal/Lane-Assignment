"""Flush: immutable memtable -> new L0 table. Depends only on ports (no Shard, no concrete classes).

Order (each step is safe to crash after; README crash table):
    1. swap: freeze active memtable, new memtable from factory, wal.rotate_all()  -> hit(MEMTABLE_FLUSH)
    2. write L0 .tmp: newest version per key + tombstones                       -> hit(SSTABLE_WRITE)
    3. tables.publish (.tmp -> final, dir fsync)
    4. manifest.commit (adds file, raises last_flushed_seq)                      -> hit(MANIFEST_UPDATE)
    5. versions.install(new Version); delete the old WAL segments
"""

from __future__ import annotations

import threading

from tsdb.engine.version import VersionSet
from tsdb.ports import FaultInjector, FileOps, ManifestPort, MemtableFactory, MemtablePort, TableFactory, WalPort


class Flusher:
    def __init__(self, versions: VersionSet, wal: WalPort, manifest: ManifestPort, tables: TableFactory,
                 new_memtable: MemtableFactory, files: FileOps, faults: FaultInjector) -> None:
        self._versions = versions
        self._wal = wal
        self._manifest = manifest
        self._tables = tables
        self._new_memtable = new_memtable
        self._files = files
        self._faults = faults
        self._lock = threading.Lock()      # one flush at a time

    def swap_memtable(self) -> MemtablePort:
        """Step 1. Returns the frozen memtable (now immutable, still readable)."""
        raise NotImplementedError

    def flush(self, memtable: MemtablePort) -> None:
        """Steps 2-5."""
        raise NotImplementedError
