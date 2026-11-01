"""MANIFEST store (implements ports.ManifestPort): the single source of truth for live files.

Replaced as a whole with atomic rename. The rename is THE moment a flush or a compaction becomes
visible after a crash. Contains a checksum so a damaged file is detected.
"""

from __future__ import annotations

from pathlib import Path

from tsdb.model import ManifestState
from tsdb.ports import FaultInjector, FileOps


class ManifestStore:
    def __init__(self, path: Path, files: FileOps, faults: FaultInjector) -> None:
        self._path = path
        self._files = files
        self._faults = faults

    def load(self) -> ManifestState | None:
        """None for a fresh directory. Raises CorruptFileError on a bad checksum."""
        raise NotImplementedError

    def commit(self, state: ManifestState) -> None:
        """Atomic replace; faults.hit(MANIFEST_UPDATE) between write and rename."""
        raise NotImplementedError
