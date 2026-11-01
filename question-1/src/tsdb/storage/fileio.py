"""Real file operations (implements ports.FileOps). Every durability step goes through here.

Rule used everywhere: write X.tmp -> fsync(X.tmp) -> rename(X.tmp, X) -> fsync(directory).
A reader then sees the old X or the new X, never half of one.
fsync uses fdatasync where available. A failed fsync raises FatalStorageError (never retried).
"""

from __future__ import annotations

from pathlib import Path


class OsFileOps:
    def open_append(self, path: Path) -> int:
        raise NotImplementedError

    def append(self, fd: int, data: bytes) -> None:
        raise NotImplementedError

    def fsync(self, fd: int) -> None:
        raise NotImplementedError

    def fsync_dir(self, path: Path) -> None:
        raise NotImplementedError

    def close(self, fd: int) -> None:
        raise NotImplementedError

    def read_all(self, path: Path) -> bytes:
        raise NotImplementedError

    def read_range(self, path: Path, offset: int, length: int) -> bytes:
        raise NotImplementedError

    def size(self, path: Path) -> int:
        raise NotImplementedError

    def atomic_replace(self, path: Path, data: bytes) -> None:
        raise NotImplementedError

    def publish_tmp(self, tmp_path: Path, final_path: Path) -> None:
        raise NotImplementedError

    def truncate(self, path: Path, length: int) -> None:
        raise NotImplementedError

    def remove(self, path: Path) -> None:
        raise NotImplementedError

    def list_dir(self, path: Path) -> list[Path]:
        raise NotImplementedError
