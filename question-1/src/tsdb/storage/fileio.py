"""Real file operations (implements ports.FileOps). Every durability step goes through here.

Rule used everywhere: write X.tmp -> fsync(X.tmp) -> rename(X.tmp, X) -> fsync(directory).
A reader then sees the old X or the new X, never half of one.
fsync uses fdatasync where available. A failed fsync raises FatalStorageError (never retried).
"""

from __future__ import annotations

import os
from pathlib import Path

from tsdb.errors import FatalStorageError


class OsFileOps:
    def open_append(self, path: Path) -> int:
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)

    def append(self, fd: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]

    def fsync(self, fd: int) -> None:
        try:
            (getattr(os, "fdatasync", None) or os.fsync)(fd)
        except OSError as e:          # never retry: the page cache state is unknown after a failure
            raise FatalStorageError(f"fsync failed: {e}") from e

    def fsync_dir(self, path: Path) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            self.fsync(fd)
        finally:
            os.close(fd)

    def close(self, fd: int) -> None:
        os.close(fd)

    def read_all(self, path: Path) -> bytes:
        return path.read_bytes()

    def read_range(self, path: Path, offset: int, length: int) -> bytes:
        fd = os.open(path, os.O_RDONLY)
        try:
            return os.pread(fd, length, offset)
        finally:
            os.close(fd)

    def size(self, path: Path) -> int:
        return path.stat().st_size

    def atomic_replace(self, path: Path, data: bytes) -> None:
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            self.append(fd, data)
            self.fsync(fd)
        finally:
            os.close(fd)
        self.publish_tmp(tmp, path)

    def publish_tmp(self, tmp_path: Path, final_path: Path) -> None:
        """tmp must already be fsynced. Rename, then fsync the directory so the rename survives."""
        os.replace(tmp_path, final_path)
        self.fsync_dir(final_path.parent)

    def truncate(self, path: Path, length: int) -> None:
        fd = os.open(path, os.O_WRONLY)
        try:
            os.ftruncate(fd, length)
            self.fsync(fd)
        finally:
            os.close(fd)

    def remove(self, path: Path) -> None:
        path.unlink(missing_ok=True)

    def list_dir(self, path: Path) -> list[Path]:
        return sorted(path.iterdir()) if path.exists() else []

    def make_dirs(self, path: Path) -> None:
        """mkdir -p, then fsync each new directory's parent so the new entries survive a crash."""
        missing = []
        while not path.exists():
            missing.append(path)
            path = path.parent
        for directory in reversed(missing):
            directory.mkdir(exist_ok=True)
            self.fsync_dir(directory.parent)
