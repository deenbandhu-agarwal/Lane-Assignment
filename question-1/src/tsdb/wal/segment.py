"""One open WAL segment file: append bytes, fsync. No knowledge of records or batching."""

from __future__ import annotations

from pathlib import Path

from tsdb.ports import FileOps


class WalSegment:
    def __init__(self, path: Path, files: FileOps) -> None:
        self._path = path
        self._files = files
        self._fd: int | None = None

    def open(self) -> None:
        """Create/open for append; fsync the directory on create (or the file may vanish)."""
        raise NotImplementedError

    def append(self, data: bytes) -> None:
        raise NotImplementedError

    def sync(self) -> None:
        """On failure FileOps raises FatalStorageError (we never retry a failed fsync)."""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    @property
    def path(self) -> Path:
        return self._path
