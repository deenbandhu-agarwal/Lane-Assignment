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
        created = not self._path.exists()
        self._fd = self._files.open_append(self._path)
        if created:
            self._files.fsync_dir(self._path.parent)

    def append(self, data: bytes) -> None:
        self._files.append(self._fd, data)

    def sync(self) -> None:
        """On failure FileOps raises FatalStorageError (we never retry a failed fsync)."""
        self._files.fsync(self._fd)

    def close(self) -> None:
        if self._fd is not None:
            self._files.close(self._fd)
            self._fd = None

    @property
    def path(self) -> Path:
        return self._path
