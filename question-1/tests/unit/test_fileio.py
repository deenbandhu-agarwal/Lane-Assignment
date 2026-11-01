"""OsFileOps.fsync must reach the disk, not only the drive's cache."""

import sys

import pytest

from tsdb.storage import fileio
from tsdb.storage.fileio import OsFileOps


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_on_macos_fsync_uses_f_fullfsync(tmp_path, monkeypatch):
    """os.fsync on macOS leaves data in the drive cache (lost on power cut); F_FULLFSYNC flushes it.
    Measured on this Mac: 0.03 ms vs 3.7 ms per call, so plain fsync cannot be a real flush."""
    calls = []
    real = fileio.fcntl.fcntl
    monkeypatch.setattr(fileio.fcntl, "fcntl", lambda fd, cmd, *a: calls.append(cmd) or real(fd, cmd, *a))
    files = OsFileOps()
    fd = files.open_append(tmp_path / "x")
    files.append(fd, b"data")
    files.fsync(fd)
    files.close(fd)

    assert calls == [fileio.fcntl.F_FULLFSYNC]
