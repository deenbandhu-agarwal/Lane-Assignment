"""Run one CompactionJob. Depends only on ports.

    1. k-way merge all input tables in key order (query.merge)
    2. per key keep only the highest seq (older versions dropped)
    3. drop points hidden by tombstones; keep the tombstones unless job.drop_tombstones
    4. write output table(s) via TableFactory (.tmp -> publish)
    5. manifest.commit: inputs out, outputs in                       -> hit(COMPACTION_SWAP) before it
    6. versions.install(new Version); inputs are deleted when no snapshot uses them
Proof obligation (test): after any number of runs, no point lost, none duplicated.
"""

from __future__ import annotations

from tsdb.compaction.policy import CompactionJob
from tsdb.engine.version import VersionSet
from tsdb.ports import FaultInjector, ManifestPort, TableFactory


class Compactor:
    def __init__(self, versions: VersionSet, manifest: ManifestPort, tables: TableFactory,
                 faults: FaultInjector) -> None:
        self._versions = versions
        self._manifest = manifest
        self._tables = tables
        self._faults = faults

    def run(self, job: CompactionJob) -> None:
        raise NotImplementedError
