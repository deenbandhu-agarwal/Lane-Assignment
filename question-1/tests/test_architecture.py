"""Architecture rules, checked on every test run (they run now, during scaffolding).

1. Dependency inversion: swappable implementation modules may be imported only by
   tsdb.bootstrap or by modules of their own package. Everyone else must use tsdb.ports.
   Exception: tsdb.tools.* (e.g. tsdb-dump) are entry points that read one concrete file format
   on purpose; the engine never imports them.
2. Every default implementation structurally satisfies its port.
"""

import ast
import pathlib
import random

import tsdb
from tsdb import ports

SRC = pathlib.Path(tsdb.__file__).parent

# implementation module -> its package (imports from inside the same package are allowed)
SWAPPABLE = {
    "tsdb.memtable.skiplist": "tsdb.memtable",
    "tsdb.memtable.memtable": "tsdb.memtable",
    "tsdb.sstable.bloom": "tsdb.sstable",
    "tsdb.sstable.reader": "tsdb.sstable",
    "tsdb.sstable.writer": "tsdb.sstable",
    "tsdb.sstable.factory": "tsdb.sstable",
    "tsdb.storage.fileio": "tsdb.storage",
    "tsdb.storage.manifest": "tsdb.storage",
    "tsdb.catalog.inverted_index": "tsdb.catalog",
    "tsdb.catalog.series_catalog": "tsdb.catalog",
    "tsdb.wal.wal_set": "tsdb.wal",
    "tsdb.wal.routing": "tsdb.wal",
    "tsdb.engine.routing": "tsdb.engine",
}


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def test_only_bootstrap_imports_swappable_implementations():
    violations = []
    for path in SRC.rglob("*.py"):
        module = "tsdb." + ".".join(path.relative_to(SRC).with_suffix("").parts)
        module = module.removesuffix(".__init__")
        if module == "tsdb.bootstrap" or module.startswith("tsdb.tools."):
            continue
        for imported in _imports(path):
            owner = SWAPPABLE.get(imported)
            if owner and not module.startswith(owner + "."):
                violations.append(f"{module} imports {imported}")
    assert not violations, "depend on tsdb.ports instead:\n" + "\n".join(sorted(violations))


def test_default_implementations_satisfy_ports(tmp_path):
    from tsdb.catalog.inverted_index import InvertedIndex
    from tsdb.engine.routing import SingleShardRouter
    from tsdb.faults import NoFaults
    from tsdb.memtable.memtable import Memtable
    from tsdb.memtable.skiplist import SkipList
    from tsdb.sstable.bloom import BloomFilter, BloomFilterFactory
    from tsdb.storage.fileio import OsFileOps
    from tsdb.storage.manifest import ManifestStore
    from tsdb.wal.routing import HashWalRouter

    store = SkipList(random.Random(1))
    files = OsFileOps()
    checks = [
        (store, ports.OrderedStore),
        (Memtable(store, 1024, 100, 1000), ports.MemtablePort),
        (BloomFilter(64, 7), ports.MembershipFilter),
        (BloomFilterFactory(), ports.MembershipFilterFactory),
        (files, ports.FileOps),
        (NoFaults(), ports.FaultInjector),
        (ManifestStore(tmp_path / "MANIFEST", files, NoFaults()), ports.ManifestPort),
        (InvertedIndex(), ports.PostingSource),
        (HashWalRouter(1), ports.WalRouter),
        (SingleShardRouter(), ports.ShardRouter),
    ]
    missing = [f"{type(obj).__name__} !~ {port.__name__}" for obj, port in checks if not isinstance(obj, port)]
    assert not missing, missing
