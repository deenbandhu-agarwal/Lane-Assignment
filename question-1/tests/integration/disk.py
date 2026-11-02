"""Look at the table files a test database left on disk (black box: path + file format only)."""

from pathlib import Path

from tsdb.model import TimeWindow
from tsdb.sstable.bloom import BloomFilterFactory
from tsdb.sstable.reader import SSTableReader
from tsdb.storage.fileio import OsFileOps


def tables(data_dir: Path) -> list[tuple[TimeWindow, SSTableReader]]:
    """Every live .sst under shard-0/sst/<size>/<start>/, opened. Call with the database closed or idle."""
    out = []
    for path in sorted((data_dir / "shard-0" / "sst").rglob("*.sst")):
        window = TimeWindow(int(path.parent.parent.name), int(path.parent.name))
        reader = SSTableReader(path, window, OsFileOps(), BloomFilterFactory())
        reader.open()
        out.append((window, reader))
    return out
