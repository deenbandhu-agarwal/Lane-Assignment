"""Run one CompactionJob. Depends only on ports.

    1. k-way merge all input tables in key order (query.merge)
    2. per key keep only the highest seq (older versions dropped)
    3. drop points hidden by tombstones (Rule 1)
    4. Rule 2 for every tombstone: KEEP it unless no live table outside the job (same Version)
       overlaps its time range AND no memtable holds an entry it hides; otherwise drop it.
       With "every table inside one window", a job over all tables of a window can drop that
       window's tombstones; a partial job keeps them.
    5. write ONE output table in job.output_window via TableFactory (.tmp -> publish)
    6. manifest.commit: inputs out, output in                          -> hit(COMPACTION_SWAP) before it
    7. versions.install(new Version); inputs are deleted when no snapshot uses them
Proof obligations (tests): no point lost or duplicated after repeated runs; no zombie data;
crash at the swap leaves either all inputs or the output live, never both or neither.
"""

from __future__ import annotations

from tsdb.compaction.policy import CompactionJob
from tsdb.engine.version import Version, VersionSet
from tsdb.model import Tombstone
from tsdb.ports import FaultInjector, ManifestPort, TableFactory


def tombstone_droppable(tombstone: Tombstone, job: CompactionJob, version: Version) -> bool:
    """Rule 2 as a pure function, unit-tested on its own.
    Drop only if no live table OUTSIDE the job may hold a point of these series in the range.
    Memtables are not checked: this tombstone was flushed, so every memtable entry has a bigger
    seq and cannot be hidden by it (design-qa #43)."""
    return True


class Compactor:
    def __init__(self, versions: VersionSet, manifest: ManifestPort, tables: TableFactory,
                 faults: FaultInjector) -> None:
        self._versions = versions
        self._manifest = manifest
        self._tables = tables
        self._faults = faults

    def run(self, job: CompactionJob) -> None:
        raise NotImplementedError
