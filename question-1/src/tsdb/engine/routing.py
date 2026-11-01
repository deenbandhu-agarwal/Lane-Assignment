"""Shard routing (implements ports.ShardRouter). Today: one shard. Later: consistent hashing on the
series key TEXT (ids are shard-local) as a new class chosen in bootstrap."""

from __future__ import annotations

from tsdb.model import SeriesKey


class SingleShardRouter:
    def route(self, key: SeriesKey) -> int:
        return 0

    def all_shards(self) -> range:
        return range(1)
