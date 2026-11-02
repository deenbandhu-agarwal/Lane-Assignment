# Question 1: an LSM-tree time-series database

A single-node, embedded time-series database with a REST API. Everything below the web framework
is written from scratch: WAL, skip-list memtable, SSTable format, Bloom filter, tag index,
compaction, crash recovery. No database, key-value store or tree library is used.

Python 3.14t (free-threaded, **GIL off**), FastAPI, pytest. Standard library only inside the engine.

- [`DESIGN.md`](DESIGN.md): the design in two pages (structures, trade-offs, what was cut, production hardening)
- [`docs/design-qa.md`](docs/design-qa.md): every design question raised while building, with the answer and outcome, including corrections and measured bugs
- [`docs/api-contract.md`](docs/api-contract.md): the API contract and filter grammar
- [`bench/results.md`](bench/results.md): raw benchmark output

## Run

| What | Command |
|---|---|
| All tests (offline, Linux container) | `docker compose run --rm --build test` |
| Server on `localhost:8080` | `docker compose up --build` |
| Benchmark (writes `bench/out/results.md`) | `docker compose run --rm --build bench` |
| Local, free-threaded 3.14t | `make setup && make test` · `uv run python -m tsdb` · `uv run python bench/run.py` |
| Look inside any data file | `uv run tsdb-dump <file or folder> [--hex]` |

Settings are environment variables `TSDB_<FIELD>` for every field of [`EngineConfig`](src/tsdb/config.py)
(e.g. `TSDB_DATA_DIR`, `TSDB_MEMTABLE_MAX_ENTRIES`, `TSDB_WINDOW_STEPS_MS=3600000,21600000,86400000`).

```bash
curl -X POST localhost:8080/write -H 'content-type: application/json' -d '[
  {"metric":"cpu","tags":{"host":"h1","region":"us-east"},"timestamp":1730368800000,"value":0.42},
  {"metric":"cpu","tags":{"host":"h1","region":"us-east"},"timestamp":1730368860000,"value":0.50}]'
# {"written":2}            <- only after the WAL fsync

curl 'localhost:8080/query?metric=cpu&filter=(region=us-east%20OR%20region=us-west)%20AND%20host!=h2&from=1730368800000&to=1730372399999&agg=avg&bucket=5m'
curl 'localhost:8080/series?filter=region=us-east'
curl -X DELETE 'localhost:8080/series?metric=cpu&filter=host=h1&from=1730368800000&to=1730368859999'
```

| Endpoint | Does | Errors |
|---|---|---|
| `POST /write` | Batch of points; whole batch or nothing | 400 names the bad point: `{"error":…,"detail":{"index":1}}` |
| `GET /query` | `metric`, `filter?`, `from`, `to` (both inclusive, ms), `agg?` (`avg sum min max count`), `bucket?` (`500ms 10s 5m 1h 1d`) | 400 with `detail.position` for a bad filter; 400 above 10,000 series or 5,000,000 points read |
| `GET /series` | Series matching `metric?` + `filter?`; answered from the tag index only | |
| `DELETE /series` | Range delete for the series matching `metric?` + `filter?` (one of them required) | |

Filter grammar: `=`, `!=`, `AND`, `OR`, parentheses; `AND` binds tighter; values may be `"quoted"`.
Buckets start at multiples of the bucket size from the epoch; empty buckets are left out.
`agg` without `bucket` gives one value for the whole range.

## Architecture

```
 HTTP (FastAPI, thread pool) ──► Database ──► Shard (one today; the boundary for sharding later)
                                                │
   write ─► series id (catalog) ─► WAL group commit: append, fsync, apply ─► memtable (skip list)
                                                                                 │ full or window closed
   flush thread ◄───────────────────────────────────────────────────────────────┘
      └─► one SSTable per time window ─► MANIFEST commit ─► old WAL segment deleted
   compaction thread: size-tiered inside time windows (1 h → 6 h → 1 day), one job at a time
   read ─► tag index ─► snapshot (Version + seq) ─► memtables + SSTables in range ─► merge ─► aggregate
```

| Package | Responsibility |
|---|---|
| `api/` | Request validation, JSON errors, status codes |
| `engine/` | `Database`, `Shard`, `Version`/snapshots, `LiveState` (the only MANIFEST writer), flush, recovery, background threads |
| `wal/` | Record framing, segments, the group-commit writer, replay |
| `memtable/` | Skip list (from scratch), memtable with versions and tombstones |
| `sstable/` | File format, writer, reader with a forward cursor, Bloom filter |
| `compaction/` | Policy (which files) and compactor (merge, drop, swap) |
| `catalog/` | Series key ↔ id (`series.log`), tag inverted index |
| `query/` | Filter parser and evaluator, merge-on-read, aggregation, executor |
| `storage/` | fsync and atomic replace, MANIFEST, folder layout |

Every component boundary is a `Protocol` in [`ports.py`](src/tsdb/ports.py); only
[`bootstrap.py`](src/tsdb/bootstrap.py) picks the classes, and a test enforces it. Swapping the skip
list for a red-black tree is one new class and one registry line.

### Memtable: why a skip list

A sorted map of `(series_id, timestamp, -seq) → value`, so every version of a point is kept, newest
first, and a series is one contiguous range. A skip list was chosen over a balanced tree because an
insert only changes neighbour pointers: readers walk it **without a lock** while the single writer
inserts (a tree rotation would move nodes under a reader). Heights are coin flips with p = 1/4,
at most 12 levels (4¹² ≈ 16.7 M, far above one memtable). A memtable is swapped out when its
size estimate (100 bytes per entry) reaches 64 MB, about 671,000 entries (hard cap 2,000,000).

### Tag index and `!=` without scans

`key=value → set of series ids`, plus `metric → ids`. `AND` intersects, starting from the smallest
set; `OR` unions. `k!=v` is `ids of the metric − ids(k=v)`: one set difference on the index, never
a scan of the data (series without tag `k` match, as in Prometheus).

## On-disk format

```
shard-0/
  MANIFEST                    JSON + "crc32 xxxxxxxx": live tables per window, next file no, WAL segment
  series.log                  framed records: id u32 | JSON [metric, [[k, v], ...]]
  wal/000002.log              WAL segment (one per memtable)
  sst/<size_ms>/<start_ms>/000001.sst   one SSTable, inside exactly one time window
```

**WAL record** (also used for `series.log`): `length u32 | crc32 u32 | payload`.
A cut or bad record stops replay there and the file is truncated to the last good record.

```
PUT     type=1 u8 | seq u64 | series_id u32 | timestamp i64 | value f64            29 bytes
DELETE  type=2 u8 | seq u64 | from i64 | to i64 | n u32 | series_id u32 × n
```

**SSTable** (little-endian; [`format.py`](src/tsdb/sstable/format.py) is the single source of truth):

```
 byte 0 ┌──────────────────────────────────────────────────────────────┐
        │ HEADER      magic "TSST" | version u16 | reserved u16  (8 B) │
        ├──────────────────────────────────────────────────────────────┤
        │ DATA BLOCK  count u32 | entry × count | crc32 u32            │  ~4 KB each,
        │   entry =   series_id u32 | timestamp i64 | seq u64 | f64    │  28 B, sorted by
        │ DATA BLOCK  …                                                │  (series, ts)
        ├──────────────────────────────────────────────────────────────┤ ◄─┐
        │ TOMBSTONES  count u32 | (seq u64 | from i64 | to i64 |       │   │ the "tail":
        │               n u32 | series_id u32 × n)* | crc32 u32        │   │ one read
        ├──────────────────────────────────────────────────────────────┤   │
        │ SPARSE INDEX count u32 | (first series u32 | first ts i64 |  │   │
        │               offset u64 | length u32)* | crc32 u32          │   │
        ├──────────────────────────────────────────────────────────────┤   │
        │ BLOOM       m_bits u32 | k u8 | bits | crc32 u32             │   │
        ├──────────────────────────────────────────────────────────────┤ ◄─┘
        │ FOOTER (74 B, read FIRST at size − 74): offsets + lengths of │
        │   tombstones, index, Bloom | min/max ts | min/max series |   │
        │   point count | version u16 | crc32 u32 | magic "TSST"      │
 end    └──────────────────────────────────────────────────────────────┘
```

Opening a table = 2 reads (footer, then the tail). A point read = 1 block read, found by binary
search in the sparse index. Every part has its own checksum; a mismatch is `CorruptFileError`.

A real table, printed by `tsdb-dump` (2 series, one delete, then a flush):

```
SSTABLE shard-0/sst/3600000/1730368800000/000001.sst  (258 bytes)  window 1 h starting 2024-10-31 10:00:00.000
[FOOTER] bytes 184-257  (read FIRST)  checksum OK
  tombstones at byte 100, 40 bytes
  index      at byte 140, 32 bytes
  bloom      at byte 172, 12 bytes
  series min 1  max 2   points 3
[TOMBSTONES] bytes 100-139  checksum OK
  DELETE seq 4: series [2]  from 2024-10-31 10:00:00.000 (1730368800000)  to 2024-10-31 10:01:00.000 (1730368860000)
[SPARSE INDEX] bytes 140-171  checksum OK
  block 0: first key (series 1, 2024-10-31 10:00:00.000 (1730368800000))  ->  byte 8, 92 bytes
[DATA BLOCK 0] bytes 8-99  3 point(s)  checksum OK
  series  time                                      seq  value
       1  2024-10-31 10:00:00.000 (1730368800000)     1  30.1
       1  2024-10-31 10:01:00.000 (1730368860000)     3  30.4
       2  2024-10-31 10:00:00.000 (1730368800000)     2  32.5
```

Series 2's point (seq 2) is still in the file next to the delete that hides it (seq 4): flush keeps
both, reads apply the delete, and compaction removes both later.

## Semantics

| Question | Answer | Proved by |
|---|---|---|
| Same series + timestamp written twice | **Last write wins** by sequence number (one global counter per shard). Also inside one batch. A query returns one point per timestamp | `test_semantics.py`, `test_compaction.py` (seeded oracle over 8 compaction rounds) |
| What a delete does to data already in SSTables | A **range tombstone** (fixed series ids + `[from, to]`) is written to the WAL like a write. It hides every point of those series in the range with a **smaller seq** (Rule 1). A point written later is visible. Compaction drops the hidden points, and drops the tombstone only when no table outside the job may hold those series in that range (Rule 2) | `test_semantics.py` (memtable, table, compacted, after restart), `test_rule2.py` |
| What a 200 on `/write` guarantees | The batch is in the WAL **and fsynced** (Linux `fdatasync`; macOS `F_FULLFSYNC`) before the reply. Group commit shares one fsync between all waiting requests. A failed fsync is never retried: the error is kept, every later write gets 500, and a restart replays the WAL | `tests/crash/` (below), `test_wal_writer.py` |
| A request with no answer (crash mid-request) | All or nothing **per point**: each point is either there or not after restart | crash-test oracle |
| A crash at any moment | Restart sees exactly the acknowledged data. Files are replaced atomically (`tmp → fsync → rename → fsync dir`); recovery deletes leftovers | `tests/crash/` |

**Crash tests** run the real server as a child process and kill it with SIGKILL, either at a named
point (`TSDB_CRASH_AT`) or at a random moment. After restart, for every point: the value equals the
model of confirmed requests, or that model plus the one request in flight. No `.tmp` or unlisted
table may remain. The harness itself was checked by breaking the engine on purpose (no WAL replay,
WAL deleted before the MANIFEST commit, leftovers kept, compaction inputs deleted early): every break
failed a test.

| Crash point | State at the crash | After restart |
|---|---|---|
| WAL append | bytes written, not fsynced, no reply | cut tail truncated; the request is all-or-nothing |
| Memtable flush | memtable frozen, no table yet | WAL replays it |
| SSTable write | half a `.tmp` table | `.tmp` deleted, WAL replays |
| MANIFEST update | `MANIFEST.tmp` written, not renamed | old MANIFEST used, unlisted table deleted, WAL replays |
| Compaction swap | output published, MANIFEST not switched | output is unlisted → deleted; inputs still live |
| kill -9 at random, 20 rounds, 4 client threads | anything | every confirmed write and delete holds |

**Consistent reads.** A query takes a snapshot: the current `Version` (memtables + table set,
reference-counted, so compaction never deletes a file under a running query) and the last applied
seq. A stress test (1 writer, 3 readers, flushes and compactions every few ms) checks that a batch is
seen whole or not at all; it found two real bugs, both fixed ([design-qa #52](docs/design-qa.md)).

## Compaction

**Size-tiered inside time windows.** Every table belongs to one window. Flush always writes the
smallest window (1 h), so a late point gets its own small table, never a rewrite of old data.
- **Size-tiered:** a 1 h window with 4 tables is merged into one.
- **Move up:** when every 1 h child of a 6 h window is closed (data time past its end + 1 h),
  they become one 6 h table; the same for 6 h → 1 day.
- **Late data:** small tables inside a moved-up window are merged into it once they reach 10 % of
  its size (so a single late point does not rewrite a day of data).

Why not leveled: time-series data arrives mostly in time order, so windows rarely overlap, and a
query for a time range skips whole windows by their bounds (see the benchmark: 6 of 7 tables skipped
by time). Leveled compaction would rewrite data again at every level for no read benefit here.

## Bloom filter

One filter per SSTable over its **series ids** (point lookups are by series, not by timestamp).
For n ids and a target false-positive rate p:

```
m = ⌈ −n · ln p / (ln 2)² ⌉  bits   (rounded up to whole bytes)      k = round(m / n · ln 2)
n = 10,000, p = 0.01  →  m = 95,856 bits (≈ 11.7 KB, 9.6 bits per id),  k = 7
```

Double hashing: `h1 = FNV-1a(id)`, `h2 = crc32(id) | 1`, positions `(h1 + i·h2) mod m` for `i < k`.
Measured: **1.001 %** false positives over 100,000 absent ids (target 1 %).

## Benchmark

`uv run python bench/run.py` (seeded; raw output in [`bench/results.md`](bench/results.md)).
10,000,000 points over 10,000 series (`cpu{host, region, service}`, one point per series every 10 s).

Two runs: the development Mac (macOS, real `F_FULLFSYNC`) and the Docker image on the same Mac
(Linux VM). Raw output: [`bench/results.md`](bench/results.md) (Mac), [`bench/out/results.md`](bench/out/results.md) (Docker).

| Measurement | macOS | Docker (Linux VM) |
|---|---:|---:|
| Memtable inserts, **1 thread**, 10 M points (target ≥ 100 K/s) | **345 K/s** | **321 K/s** |
| End to end in-process, 10 M points, 8 writers, fsync before every reply | 59 K/s | 133 K/s |
| … batch latency (100 points) p50 / p99 | 13.0 / 26.4 ms | 5.4 / 15.9 ms |
| … points per fsync (group commit) | 397 | 398 |
| Over HTTP (JSON), 5 s | 70 K/s | 140 K/s |

Queries on the 10 M points after flush and compaction (8 tables, 3 of them in any 1 h range):

| Query | p50 / p95 / p99 ms (macOS) | p50 / p95 / p99 ms (Docker) | blocks read |
|---|---:|---:|---:|
| 1 series, raw, 1 h | 2.7 / 4.3 / 6.6 | 2.3 / 2.7 / 3.1 | 5–7 |
| 1 series, count, all time | 7.0 / 8.4 / 10.3 | 5.4 / 6.5 / 11.3 | 12–13 |
| 10 series (`OR`), max per 1 min, 1 h | 10.7 / 15.4 / 27.7 | 8.5 / 16.6 / 28.2 | 54–55 |
| 499 series (`AND`, `!=`), avg per 5 min, 1 h | 326 / 387 / 398 | 227 / 336 / 370 | ~2,600 |

**How to read these numbers.**
- The memtable target (≥ 100 K inserts/s on one core) is met by the skip list alone.
- End-to-end writes are limited by fsync, not by the CPU. A real flush to disk costs ~3.7 ms on the
  development Mac (`F_FULLFSYNC`), and group commit puts about 400 points into each fsync.
- In Docker on the same Mac the same load runs about 2× faster. That is most likely because the
  Linux VM's `fdatasync` does not wait for the physical disk the way `F_FULLFSYNC` does, so the Mac
  numbers are the honest ones.
- Before the fsync fix, macOS's plain `fsync` (0.03 ms, does not reach the disk) showed 315 K points/s;
  that number was thrown away ([design-qa #53](docs/design-qa.md)).
- Time pruning works: a 1 h query skips 5 of 8 tables by their window. The Bloom filter skipped
  nothing in this load, because every table holds all 10,000 series (all series write every 10 s).
  It pays off when series are sparse across time, e.g. hosts that come and go.
- The 499-series query reads ~2,600 blocks: one or two blocks per series per table. Its cost is
  Python decoding 28-byte entries, which is where a compact block encoding would help most.
- More WAL files were measured slower (1 WAL ~70 K, 2 WALs ~52 K, 4 WALs ~28 K points/s), so the
  multi-WAL code was removed ([#54, #55](docs/design-qa.md)).

## Assumptions and known gaps

- One node, one shard. The `Shard`/`ShardRouter` boundary is where hash sharding would go.
- Series ids, the catalog and the tag index live in memory and are rebuilt from `series.log` at
  start. Fine for 10 K–1 M series; beyond that the index would need its own files.
- Values are stored raw (28 bytes per point). Delta-of-delta timestamps and XOR-compressed values
  (Gorilla) would cut this ~10×; left out to keep the format easy to inspect and explain.
- A series whose points are all deleted is still listed by `/series` (the series exists; its data
  is gone).
- The once-per-day late-merge pass is not built (`late_merge_interval_ms` is unused); late tables
  below 10 % wait, and reads apply them correctly in the meantime.
- SIGKILL keeps the operating-system page cache, so the crash tests do not imitate a power cut;
  fsync correctness rests on the fsync rules above and the failing-fsync tests.
- No authentication, TLS or rate limiting on the API.
