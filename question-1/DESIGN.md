# Question 1: Design

A single-node LSM-tree time-series database. How to run it, the byte layout, the semantics and the
benchmark are in the [README](README.md). Every design question raised while building it, with
corrections, is in [`docs/design-qa.md`](docs/design-qa.md) (#n below points there).

## 1. Data structures and architecture

```
POST /write ─► catalog: series key → id ─► WAL (group commit, fsync) ─► memtable ─┐
                                                                                  │ full, or its window closed
GET /query ─► tag index → ids ─► snapshot ─► memtables + SSTables ─► merge ─►    flush ─► SSTable per window
                                                                    aggregate      compaction ─► bigger windows
```

| Structure | What it is | Why this one |
|---|---|---|
| **Series catalog** | `metric + sorted tags ↔ u32 id`, appended to `series.log` | Keys everywhere else are 4-byte ids, not strings. Tag text is escaped, so two different series never print the same (#42) |
| **Tag index** | `key=value → set of ids`, `metric → ids`, in memory | `AND` = intersect (smallest first), `OR` = union, `k!=v` = `metric ids − ids(k=v)`: no data scan, ever |
| **Sequence number** | one counter per shard, given at WAL append | Decides "last write wins" and what a delete hides. Clock timestamps cannot (client clocks, same ms) (#26, #27) |
| **WAL** | one append-only file per memtable, `length | crc32 | record` | One writer thread, group commit: all waiting requests share one fsync. A cut tail is detected by the length + crc and truncated (#8) |
| **Memtable** | skip list keyed `(series id ↑, timestamp ↑, seq ↓)`, every version kept | Readers walk it without a lock while one writer inserts. Keeping versions lets a running query read an exact snapshot (#9, #10) |
| **SSTable** | 4 KB blocks of 28-byte entries, tombstones, sparse index, Bloom, 74-byte footer | Footer first, then one read of the tail; a point read is 1 block. Each part has its own crc32. Each table lies inside one time window |
| **Bloom filter** | per table, over series ids, 1 % target | A query asks "does this table have series 42?", never "this timestamp". m = 95,856 bits, k = 7 for 10 K ids; measured 1.001 % (#35, #36) |
| **Range tombstone** | `seq, series ids, [from, to]`, written to the WAL like a write | Rule 1: it hides points of those series in the range with a smaller seq. Rule 2: compaction drops it only when no table outside the job may hold those series in that range (#43) |
| **MANIFEST + Version** | JSON + crc32, replaced atomically; `LiveState` is its only writer | A query holds a reference-counted `Version` (memtables + tables) and a seq: compaction never deletes a file under it (#47, #52) |

**Threads (Python 3.14t, GIL off):** an HTTP thread pool (queries run in parallel on real cores),
one WAL writer, one flush thread, one compaction thread. At most one frozen memtable waits for
flush; if the active one is also full, writers wait: a slow disk slows writes instead of growing
memory. A failed fsync is never retried: the error is kept and every later write gets 500 (#49).

**Compaction:** size-tiered inside growing time windows, 1 h → 6 h → 1 day. Flush always splits at
1 h edges; 4 tables in one window are merged into one; when all six 1 h windows of a 6 h window
are closed, they become one 6 h table (the same for 6 h → 1 day) (#37–#39).

## 2. Trade-offs

| Decision | Chose | Gave up |
|---|---|---|
| When to reply 200 | After fsync (`fdatasync` on Linux, `F_FULLFSYNC` on macOS) | Latency: p50 13 ms per 100-point batch on the Mac. Throughput is bound by the disk (~400 points per fsync) (#14, #53) |
| Number of WALs | 1. Built N, measured 1 / 2 / 4 = ~70 K / 52 K / 28 K points/s, removed N | Parallel fsyncs on disks that support them (#54, #55) |
| Memtable | Skip list, every version kept | A per-series append buffer (Prometheus style) is faster for in-order data, but the brief rules out map shortcuts. Versions cost memory until flush (#11, #13) |
| Compaction | Time windows | Leveled compaction: here every flush holds all series, so it would overlap (and rewrite) all of the next level. Time windows let a 1 h query skip 5 of 8 tables by their bounds (#37) |
| Late points | Always their own small table | More small files; in return a late point never rewrites a day of old data (#38) |
| Delete target | Series ids fixed when the delete arrives | A series created later with matching tags is not deleted (same as "delete these rows") (#41) |
| Language | Python 3.14t | Raw speed (Go would be faster), for code I can explain and change live. The memtable still does 345 K inserts/s on one thread (target 100 K) (#31–#33) |
| On-disk encoding | Raw 28-byte entries | Space: about 10× more than Gorilla (delta + XOR) encoding; in return the raw form is easy to inspect with `tsdb-dump` |
| Index | In memory, rebuilt from `series.log` at start | Start time and memory beyond ~1 M series |

## 3. What was cut and why

| Cut | Why |
|---|---|
| Multiple WALs | Built and tested, then measured slower here; ~330 lines removed (#54, #55) |
| Compression (Gorilla, delta-of-delta) | Format stays readable and easy to explain; the brief scores correctness first |
| Rollups / downsampling | Not asked. Designed to fit: build them during move-up compaction inside the same file, so they can never be stale (#40) |
| Daily late-merge pass | Late tables below 10 % of their window wait; reads are correct meanwhile |
| Sharding, replication | One node asked. `Shard` and `ShardRouter` are the boundary (#16, #28) |
| Block cache | The OS page cache serves repeat reads; a cache would not change correctness |
| Auth, TLS, rate limits | Out of scope for a storage engine exercise |

## 4. Production hardening

1. **Power-cut testing.** SIGKILL keeps the page cache, so today's crash tests cannot lose an
   un-fsynced page. Add a fault-injecting file system (LazyFS or `dm-flakey`) that drops unsynced
   writes, and run the same oracle.
2. **Corruption handling.** Every part is checksummed, but a bad table stops the read with an
   error. Production would quarantine the table, alert, rebuild from a replica, and run a
   background scrub that re-reads every crc.
3. **Disk full and back-pressure.** Refuse writes (503 with `Retry-After`) before the disk is
   full, instead of failing an fsync. Return 503 instead of blocking when flush falls behind.
4. **Observability.** Metrics for fsync latency, points per fsync, memtable size, flush and
   compaction lag, write stalls, tables and blocks read per query; a health endpoint that reports
   the "storage failed" state; structured logs per background job.
5. **Retention.** Drop whole windows past a TTL: with time windows this is a file delete, not a rewrite.
6. **Read speed.** Encode blocks compactly and decode them in native code (the 499-series query
   spends its 330 ms decoding ~2,600 blocks in Python); add a block cache with a size limit.
7. **Scale out.** Hash series to shards (one per core, then per node), replicate each shard's WAL
   (Raft or a quorum), keep the per-shard seq as the order. Persist the tag index in files once
   series count makes the start-up rebuild slow.
8. **Operations.** Backups as hard links of the immutable tables plus the MANIFEST; a version byte
   is already in every file for format upgrades; fuzz the file parsers; a long soak test with
   kill -9 and compaction running.
