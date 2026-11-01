# Question 1 — Design Q&A log

Cross-questions raised while designing the storage engine, with the answer we settled on.
Kept for the submission (design doc appendix / interview prep). Newest at the bottom.

Legend — **Outcome:** `decision` (changed the design) · `clarified` (no design change) · `deferred` (design doc / later)

---

## Data model & API

### 1. What is a "metric" and what is a "series"?
- **Answer:** Metric = what is measured (`temperature`). Tags = which one (`city=Delhi, sensor=roof`). Series = metric + the exact full tag set: one line on a graph. Tag order does not matter; a missing or extra tag makes a different series.
- **Outcome:** clarified. Series key = metric + tags sorted by key.

### 2. What does "delete a series" mean?
- **Answer:** `DELETE /series` = tag filter + time range. It erases the points of matching series inside that range (the whole series only if the range is all time). SSTables are immutable, so we write a range tombstone `{series ids, from, to, seq}` that hides older points on read and is physically applied during compaction.
- **Outcome:** decision. A write after the delete (higher seq) is visible. A tombstone may be dropped only when compacting into the last level (otherwise deleted data comes back).

### 3. What does "GET /series lists the distinct series that match a tag filter" mean?
- **Answer:** It returns which series exist (metric + tags), not their points. "Distinct" = each series once. Answered entirely from the series catalog + inverted index; no data blocks read.
- **Outcome:** clarified. Index must be rebuilt on restart (from `series.log`).

## Storage layout

### 4. How are we going to keep the data?
- **Answer:** Points keyed by `(series_id, timestamp)` (+ seq) in a memtable → flushed to immutable SSTables (sorted blocks, sparse index, Bloom on series_id, tombstone block, footer with checksums). Series catalog in `series.log`; inverted index in memory. `MANIFEST` lists live files.
- **Outcome:** decision. Key order series-first because queries are "one series over a time range".

### 5. Can one partition end up with too much data for one series?
- **Answer:** There is no per-series partition. SSTables are capped by size (~64 MB) and cut wherever the key is, so a large series spans many blocks/files; the sparse index and per-file min/max key let a query read only the blocks in `[from, to]`. Real risks are huge raw query results (cap response size, steer to aggregation) and read amplification (Bloom + time pruning + compaction).
- **Outcome:** clarified. Time-partitioned blocks (Prometheus-style) → deferred to design doc.

## Write path & WAL

### 6. What happens if the WAL write succeeds but the memtable write fails?
- **Answer:** The point is durable but invisible until restart → answers would change after restart. Rule: validate everything **before** the WAL; if memtable insert or fsync still fails, crash the process so replay makes memory = disk. "No OK" means "maybe saved", not "not saved"; retries are safe because the same series + timestamp overwrites (last write wins).
- **Outcome:** decision. Stated in README guarantees.

### 7. Where exactly is the series id lookup done?
- **Answer:** In memory, in the write path, **before** the WAL: `keyToId` hash map (sorted-tags key → id) and `idToSeries` array. New series: take a lock, re-check, assign next id, append to `series.log`, update index. Must precede the WAL because WAL records store only the id. Queries never look up by name; filter → inverted index → ids → `idToSeries` for the response.
- **Outcome:** decision. Hash map is fine here (the brief's "no Map shortcut" applies to the sorted memtable only).

### 8. Why does each WAL record need a length?
- **Answer:** The WAL is records back to back. Length tells where a record ends (records differ in size: PUT 29 B, DELETE grows with the number of series). It also detects a half-written last record after a crash (fewer bytes than the length) and tells the checksum exactly which bytes to cover. Relying on the type byte for size breaks if that byte is damaged.
- **Outcome:** clarified. Record = `length | crc32 | payload`.

## Memtable

### 9. Which data structure will the memtable use?
- **Answer:** Skip list (allowed: skip list or balanced BST). Short code, easy in-order walk for flush and range reads, and readers can walk while a writer links nodes (no rotations), which suits the "consistent reads during writes" requirement.
- **Outcome:** decision. **Correction made here:** overwrites must not replace in place (a running query could see a newer value → torn read). Key = `(series_id ↑, timestamp ↑, seq ↓)`, all versions kept; newest wins at flush.

### 10. How is a new entry's skip list level decided, and how many levels are there?
- **Answer:** Coin flip, independent of the key: start at height 1, go up while `random() < 0.25`, max 12. About 1/4 of entries per level above. 2M entries → ~11 levels used → ~25–35 steps per search. Skip list levels (memory) are not SSTable levels L0/L1 (disk): a flush always writes to L0.
- **Outcome:** decision. p = 1/4, max level 12.

### 11. Do we really need a skip list? Could a "smart" memtable bucketed by time range work?
- **Answer:** Per-series, time-ordered buffers are what real TSDBs (Prometheus) use and are faster for in-order appends. But the brief requires a skip list or BST and forbids Map-as-sorted-structure shortcuts, so replacing it risks failing a stated requirement.
- **Outcome:** decision: keep skip list. Smart memtable → design doc "what production would use".

### 12. What is the optional "last position" shortcut?
- **Answer:** A per-series pointer to the last inserted node. For an in-order point, check "new key > last node and < its next node" → insert directly on level 0 without searching from HEAD. Works for height-1 nodes (~75%); taller nodes fall back to normal search. Out-of-order points fall back too.
- **Outcome:** deferred. Add only if the benchmark misses 100K writes/s.

### 13. Should we have a separate skip list per series?
- **Answer:** Fewer steps per insert (~8 vs ~21), but more code (map of lists, safe creation of new lists during queries, per-series overhead with many series) and a gain we don't need (estimated 5–10× above target).
- **Outcome:** decision: one skip list. Per-series structures → design doc trade-off.

## Durability & write scaling

### 14. When should we fsync the WAL?
- **Answer:** Options: fsync per request, group commit, periodic fsync, never. Periodic/never can lose acknowledged writes → fail the kill -9 test. Group commit gives the same guarantee as per-request with far fewer fsyncs.
- **Outcome:** decision. Group commit; reply 200 only after `fdatasync`. fsync failure → crash. Brief's 100K/s is "into the memtable"; report it and end-to-end separately.

### 15. Can we have multiple WAL logs?
- **Answer:** Two meanings. (a) Segments one after another, one per memtable, deleted after flush: yes, already in the design. (b) Several written in parallel: possible, needs care (see 18).
- **Outcome:** clarified → led to 16–18.

### 16. Would consistent hashing of series to WALs help for a distributed system?
- **Answer:** Yes for multi-node: consistent hashing on the **series key text** (ids are node-local) minimises data movement when nodes join/leave. But the brief is single-node, and a WAL can't be split alone; the unit of distribution is a whole shard (WAL + memtable + SSTables + MANIFEST).
- **Outcome:** deferred. Code shaped as `Shard` + `pickShard(seriesKey)` (one shard today) so distribution is a one-function change. Consistent hashing + replication → design doc.

### 17. Can consistent hashing help on the same node, for more writes?
- **Answer:** More write throughput on one node comes from **splitting into N parts** (parallel writers/fsyncs), not from consistent hashing. Consistent hashing only helps when N changes; on one node N is fixed at start, so `hash % N` does the same job.
- **Outcome:** clarified.

### 18. Multiple WALs with each series pinned to one WAL: does that help?
- **Answer:** Yes, and it is safe: one series → one WAL keeps per-series order; each WAL replays independently; one global seq counter taken at append time. Needs: tombstone written to every WAL holding an affected series; all WALs rotate together on memtable swap; a small lock around skip list insert. Speed-up is uncertain (ext4 shares one journal across files), so we measure.
- **Outcome:** decision. N WAL files (config, default 1), `hash(series key) % N`; benchmark N = 1, 2, 4. **Correction made here:** "half a batch saved across two WALs" is not a problem; no OK was sent, so "maybe saved" applies.

## Read path

### 19. How is a read across many series done? Won't it become a bottleneck?
- **Answer:** Filter → sorted series ids → for each series, each source (memtable + SSTables): Bloom → sparse index → block → merge (newest seq wins, tombstones hide) → aggregate. Naive cost = series × sources. Mitigations: one forward-only cursor per file over the sorted ids (neighbouring series share blocks, each block read once); skip files by Bloom + footer min/max; compaction keeps file count low; streaming aggregation (memory = series × buckets); LRU block cache; split series across threads; per-query series/point limits. Real weak spot is the key order: "many series, short recent range" means many small scattered reads. Time-partitioned blocks (Prometheus) fix it.
- **Outcome:** decision: forward-only per-file cursors, streaming aggregation, query limits. Benchmark must include a many-series query. Block cache + parallel reads optional; time partitioning → design doc.

### 20. What is the issue with time-partitioned blocks?
- **Answer:** Nothing wrong for production, but: long single-series ranges now open many blocks (7 days / 2 h = 84); late points must go into old, closed blocks; files, index entries, compaction and MANIFEST entries multiply per block (heavy with 10K series); deletes must write tombstones into every block in range; new crash points (create/seal block). Main win is cheap retention (drop old blocks), and the brief has no retention requirement.
- **Outcome:** deferred. Design doc "what production would add".

### 21. Is there a way to get both: fast "many series, short recent range" and fast "few series, long range"?
- **Answer:** Mostly yes: group SSTables by time window inside compaction (compaction only merges files of the same window) and make windows grow with age (2h → 1 day → 1 week), as Prometheus and Cassandra's time-window compaction do. Recent queries read memtable + newest small window (older files pruned by footer min/max time). Long single-series ranges touch ~5–10 files, each a continuous read. No new storage format: same SSTables, only a rule for which files compaction merges. Costs: flush may split at a window edge; late points land in a new L0 file and are merged into their window later.
- **Outcome:** deferred to the compaction decision. Candidate: "size-tiered compaction inside growing time windows" (fits the brief's "size-tiered, justified").

### 22. How exactly does an SSTable look, and how does a read work, including tombstones?
- **Answer:** File = header (`TSST`, version) · sorted data blocks (each with checksum) · tombstone block · sparse index (first key of each block → offset) · Bloom (series ids) · fixed 72-byte footer (offsets, min/max time and series, count, checksum, magic). On open, only footer + index + Bloom + tombstones are loaded into memory; data blocks stay on disk. Read: filter → ids → collect tombstones for the series from **all** sources (a delete in a newer file hides points in an older one) → per file: footer range check → Bloom → binary search sparse index (last block whose first key ≤ (series, from)) → read block(s), verify checksum, walk until key > (series, to) → merge by time, highest seq wins → hide a point if a tombstone covers its series and time **and** tombstone seq > point seq. A point written after the delete (higher seq) stays visible.
- **Outcome:** clarified. Note: tombstone series ids are also added to the file's Bloom, so a Bloom "no" never hides a tombstone. Tombstones dropped only when compacting into the bottom level (else zombie data).

### 23. How is the footer read first?
- **Answer:** Get the file size from the OS (`fstat`), seek to `size − 72` (footer is a fixed 72 bytes), read 72 bytes, check magic `TSST` + checksum; the footer gives the offsets of index, Bloom and tombstones. It is at the end because a flush writes the file in one front-to-back pass and positions are only known after the blocks are written; a header "map" would need a gap and a seek back (and a crash risk). Fixed size = one seek, one read. Same approach as LevelDB/RocksDB/Parquet.
- **Outcome:** clarified. Bad magic/checksum/offsets → reject file (only possible from disk damage, since files enter MANIFEST after fsync).

### 24. Why is the footer always 72 bytes?
- **Answer:** We chose 13 fixed-width binary fields: 3 × (u64 offset + u32 length) for index/Bloom/tombstones = 36, min/max time 2 × i64 = 16, min/max series 2 × u32 = 8, point count u32 = 4, checksum u32 = 4, magic 4 → 72. Binary integers are always the same width whatever the value (text numbers would change length). Widths are ample (u32 lengths = 4 GB per part vs ~64 MB files). Format changes → bump version; a newer version may have a different footer size.
- **Outcome:** decision for the real format: also put a 2-byte version **inside the footer** (before the magic), so one read at the end is enough → footer 74 bytes. LevelDB uses a fixed 48-byte footer.

### 25. Why is a magic number required?
- **Answer:** A fixed 4-byte marker (`TSST`) checked before trusting any offset. Catches: a foreign file in `sst/`, a file cut short by a crash, a zero-filled tail after a crash, and our own offset bugs. Cheaper than the checksum and gives a distinct error ("not our file / incomplete" vs "our file but damaged"). Header copy identifies the file when read from the start (tools, hexdump); footer copy is written last, so its presence proves the writer reached the end. Cost 8 bytes per file. Same idea as PNG/PDF/ZIP; Parquet uses `PAR1` at both ends.
- **Outcome:** clarified.

### 26. How do real systems tell "old data the delete should hide" from "new data written after the delete"? With timestamps?
- **Answer:** The point's **data time** (10:00) cannot do it: a rewrite of 10:00 after the delete has the same data time. Options are **write time** (a clock) or a **sequence number**. LevelDB/RocksDB: sequence numbers (range deletes carry a seq). Cassandra: write timestamps on every cell and tombstone (risk: clock skew/jumps can wrongly hide new data or miss old data). HBase: cell timestamps + internal seq ids (known trap: a put with an older timestamp sent after a delete stays hidden). Prometheus: tombstones are data-time ranges only; works because it mostly rejects old timestamps. On one node, seq is a logical clock: strictly increasing, never equal, no clock problems.
- **Outcome:** decision: keep seq. Multi-node later: one seq per shard is enough (a series lives in one shard); hybrid logical clocks (CockroachDB) only if one operation must be ordered across shards. Mention Cassandra's approach in the design doc.

### 27. Then why does Cassandra use write timestamps?
- **Answer:** Cassandra is leaderless: any of the (typically 3) replicas accepts writes, and replicas receive writes in different orders. Per-node counters can't be compared across replicas; a global counter would add a network trip to every write and stop writes when it is unreachable, breaking Cassandra's "always writable" goal. Write timestamps let each replica resolve conflicts on its own (bigger timestamp wins), so all replicas converge regardless of arrival order, with no coordination. Price: clock skew (NTP required), possible wrong hide/miss, Paxos "lightweight transactions" when strict order is needed. Others: Raft-based systems (etcd, TiKV, CockroachDB ranges) use the leader's log index (a per-shard seq); Spanner uses TrueTime; CockroachDB uses hybrid logical clocks.
- **Outcome:** clarified. We have one ordering point (one node, or one owner per shard later), so seq fits; our future sharding model is the Raft/leader model, not Cassandra's.

### 28. With per-shard seq, how does repartitioning (moving a series to another shard) work?
- **Answer:** Problem: shard counters differ (A at 5,000, B at 300); moved points keep seq ~4,900, so a new delete on B (seq 301) would fail to hide them. Seq is only compared within one series, and a series has one owner at a time, so we only need seq to keep rising for the moved series. Fix (Lamport clock rule): before applying moved data, B sets `counter = max(counter, max incoming seq) + 1`; moved points keep their seq and everything new on B is larger. Move steps: snapshot as of seq S (B bumps counter) → stream source WAL entries for the series after S in order → brief pause + flip routing table (saved atomically, like MANIFEST) → source drops its copy later. A crash before the flip leaves A as owner (B's partial copy discarded); after it, B. Simpler variant: copy only the resolved view (newest per point, deleted points removed) and restamp with B's seqs. Consistent hashing decides *which* series move; this decides *how*.
- **Outcome:** deferred (design doc). Interview line: "seq is per shard; on a move we apply max(local, incoming)+1, so per-series order holds."

### 29. What is the worst-case disk read cost of a query?
- **Answer:** Only reading data blocks touches the disk during a query; filter, tombstones, memtable, footer/Bloom/sparse-index lookups, merge and aggregation are in memory. Opening a file costs 2 reads once (footer, then the contiguous tail: tombstones + index + Bloom). Block reads ≈ **S × F × (1 + P/b)** (S series, F candidate files, P points in range, b ≈ 146 points per 4 KB block), capped at all blocks of the touched files thanks to forward-only cursors. Best (1 series, 1 h, 1 file) ≈ 4 blocks; worst (10K series, last 5 min, 10 overlapping files) ≈ 100K blocks ≈ 400 MB, using ~1 KB of every 4 KB block read (~0.1–0.3 s cached, ~1–3 s uncached NVMe: estimates). Bloom false positives add ~1% × S × F reads.
- **Outcome:** clarified + design note: metadata (tombstones, index, Bloom, footer) kept contiguous at the file tail. Cost is driven by S × F; S is the user's choice, **compaction controls F** (leveled ≈ 1 file per level; time windows → F ≈ 1–2 for recent queries). Feeds the compaction decision.

### 30. Isn't collecting tombstones for every query too much memory?
- **Answer:** Size = 24 bytes + 4 bytes per series id. Normally small (deletes are rare; a 10K-series delete ≈ 40 KB), but unbounded under misuse (1M big deletes ≈ 40 GB). Controls: (1) compaction drops tombstones once their data reaches the bottom level, so only "deletes since last compaction" are held; (2) trigger early compaction when a file's tombstone bytes pass a limit (e.g. 1 MB), like RocksDB's compact-on-deletion; (3) at file open, build a per-series map `series_id → [(from, to, seq)]` so a query does an O(1) lookup instead of scanning every delete's id list; (4) last resort: keep the tombstone block on disk sorted by series id and read it on demand. Never merge overlapping tombstones with different seqs (it would hide points written between the two deletes).
- **Outcome:** decision: (1)–(3); (4) only if the benchmark needs it. **Correction:** "collect tombstones from all sources" means a per-series map lookup, not a scan.

### 31. What about Python as the language?
- **Answer:** Measured a pure-Python skip list (our design, `__slots__` nodes, p = 1/4, max 12), single thread, Python 3.9.6 on this Mac, 10K series interleaved in time order: 384K inserts/s at 200K entries, 185K/s at 1M, **155K/s at 2M** (full 64 MB memtable). Brief target is 100K/s into the memtable → passes with ~1.5× margin (3.12 typically 20–40% faster; not measured, Docker was down). Trade-offs vs Go: GIL means reads during compaction take turns (still correct); fsync releases the GIL so group commit / N WALs still overlap I/O; same language as Q2; easy to explain live if it is the strongest language.
- **Outcome:** decision (2026-11-01): **Python**. User is not confident in Go, and the brief requires explaining line by line and changing code live; Python meets the measured target. Setup: 3.12 in Docker, FastAPI, pytest; "last position" shortcut (#12) is the backup if margin shrinks.

### 32. Hasn't the GIL been removed in the latest Python, making it truly parallel?
- **Answer:** Only in a separate build. 3.13 shipped an experimental free-threaded build (`python3.13t`, PEP 703) with a large single-thread slowdown; 3.14 made it officially supported (PEP 779) with a much smaller slowdown (~5–10%), but the default `python3.14` still has the GIL. Whether 3.15 made it default: not verified. Effect for us: truly parallel reads/compaction/WAL writers, but races the GIL used to hide become real (every shared counter/dict/list needs a lock); library support and Docker setup need checking.
- **Outcome:** decision (if Python): build and test on standard Python (3.12/3.13); write code GIL-independent (explicit locks, bottom-up skip list links); optionally benchmark + stress-test on 3.14t and report both.

### 33. Use free-threaded Python 3.14t?
- **Answer:** Yes (user decision). Local `.venv` on CPython 3.14.5 free-threaded via uv; Docker installs 3.14t with uv (no official image) and sets PYTHON_GIL=0. Measured the same pure-Python skip list, 2M entries, one thread, 2 runs each: **3.14t ≈ 470–495K inserts/s vs normal 3.14 ≈ 220–230K/s** (free-threaded faster here; likely its allocator/GC on this node-allocation-heavy workload, not investigated). FastAPI/pydantic import without re-enabling the GIL (checked by a test).
- **Outcome:** decision. Code uses explicit locks (no reliance on the GIL); a scaffold test asserts the GIL is off. Docker Compose only (no OrbStack-specific features); on this Mac a Docker engine must still be running to use it.

### 34. Is the code SOLID with dependency injection, so any implementation (e.g. skip list -> RB tree) can be swapped by changing only the dependency?
- **Answer:** First scaffold violated DIP (Shard built its own collaborators; Flusher/Compactor/Recovery/Background took the whole Shard; SkipList made its own RNG; global fault/fsync functions; hard-wired routing/aggregations). Fix: `tsdb/ports.py` holds a Protocol for every component boundary (OrderedStore, MemtablePort/Factory, MembershipFilter/Factory, TableReader/Cursor/Writer/Factory, ManifestPort, WalPort, WalRouter, ShardRouter, PostingSource, SeriesResolver, Aggregator, FileOps, FaultInjector, TimeSeriesStore); plain constructor injection, no DI framework; `tsdb/bootstrap.py` is the only composition root, with registries (`ORDERED_STORES`, `COMPACTION_POLICIES`) selected by config (`memtable_structure`, `compaction_policy`). Skip list -> RB tree = new OrderedStore class + one registry entry + config value. Aggregations are a registry (OCP). A failing-fsync FileOps and EnvFaults are injected for crash tests.
- **Outcome:** decision. Enforced by `tests/test_architecture.py`: (1) swappable implementation modules may only be imported by bootstrap or their own package; (2) every default implementation structurally satisfies its port (this test caught `OsFileOps` missing `list_dir`). Note for RB tree: rotations move nodes under readers, so it needs a read lock or copy-on-write to keep lock-free reads.

### 35. Bloom filter per SSTable, or one for all SSTables?
- **Answer:** Per SSTable. The filter's job is "which files can I skip for series X"; one global filter only says "is X in any file" (the catalog already knows that exactly) and can't point to a file. A global filter also can't remove bits when compaction deletes files/points (would need a counting Bloom), must be rewritten and made crash-safe on every flush/compaction, and breaks "files never change". Per-file filters are written once inside the immutable file and vanish with it (same as RocksDB/LevelDB). Alternative: exact per-file series-id list (40 KB at 10K series, exact) beats Bloom at low cardinality, but grows to 4 MB at 1M series vs ~1.2 MB Bloom, and the brief requires Bloom.
- **Outcome:** decision: keep per-SSTable Bloom. Exact list → design doc; swappable via the `MembershipFilter` port.

### 36. How do Cassandra and other databases place Bloom filters?
- **Answer:** All per file or finer, never global. Cassandra/ScyllaDB: one per SSTable (`Filter.db`, off-heap), on the partition key, `bloom_filter_fp_chance` per table (default differs by compaction strategy). RocksDB: one "full filter" per SST by default; partitioned filters for big files; whole-key or prefix Bloom; Ribbon filter (~30% smaller); optional memtable Bloom. LevelDB: filter block per SST, one small filter per ~2 KB of data, pluggable FilterPolicy. HBase: per HFile, chunked "compound" Bloom, row or row+column. ClickHouse: skipping index per granule group. Parquet: per column chunk. Prometheus: no Bloom; exact per-block inverted index. Pattern: filter key matches the read pattern; our series-id filter is like RocksDB's prefix Bloom. (Defaults not re-checked against current docs.)
- **Outcome:** clarified; confirms #35. At ~12 KB per 64 MB file, no partitioning needed.

## Compaction

### 37. Which compaction strategy? (discussion opened)
- **Answer:** Our data arrives in time order with every series writing continuously, so every flush file holds ~all series but its own time slice: the per-series Bloom rarely skips files (kept for the brief, FPR reported); **footer min/max time is the real pruning**, so compaction must keep file time ranges narrow. Leveled is a poor fit: keys are series-first and every L0 file spans all series, so each flush overlaps (and rewrites) all of L1. Plain size-tiered works if it merges only time-adjacent files. Size-tiered **inside time windows** (TWCS): 1 file per window per query range, lowest rewrite, clean tombstone cleanup when a window becomes one file. General tombstone-drop rule (correct for any strategy): drop only if no live file outside the compaction could hold a point it hides.
- **Outcome:** leaning to time windows (fixed 1 h windows first, growing windows → design doc); pending confirmation of window size and merge threshold.

### 38. Must late points go to their own window (must flush split by window)?
- **Answer:** Not for correctness (read rule + general tombstone-drop rule keep answers right either way), only for efficiency. Cassandra's TWCS does not split; a file is placed in the window of its max timestamp, so one late point stretches the file's range (worse time pruning), its old window can never become one file, and tombstones there may never be droppable; Cassandra documents that TWCS handles out-of-order writes badly. Splitting keeps every file inside one window at the cost of extra small files. Middle ground: split only points more than one window late. Very late points re-open closed windows; limit re-compaction of closed windows (≥ 2 files and periodic).
- **Outcome:** decision: first chose "split only points more than one window late", then **changed to always split at window edges**. **Correction:** keeping an edge-crossing memtable as one file makes that file span two windows, which breaks "every file inside one window" and forces cross-window merges before tombstones can be dropped; the saving was at most one small file per window.

### 39. Can window sizes differ by age (different scaling at different levels)?
- **Answer:** Yes: growing windows, e.g. 1 h → 6 h → 1 day, each a multiple of the previous and aligned to the epoch, so windows nest exactly and "every file inside one window" holds at every step (Prometheus grows blocks 2h → 6h → 18h → 54h …). Flush splits at the smallest window; size-tiered inside a window; when all small windows inside a bigger one are closed, merge them into one file of the bigger window; tombstones are dropped in that merge (it covers the whole range: Rule 2). Recent many-series queries touch ~1–2 files; a 7-day single-series query ~7 files instead of 168. "Closed" is judged on data time (newest timestamp written + grace), not wall clock (deterministic tests; loadgen timestamps may be in the past). Late points into an already-merged big window stay as small extra files until they reach ~10% of the big file or a daily pass.
- **Outcome:** decision: **compaction = size-tiered inside growing time windows**, steps **1 h → 6 h → 1 day**, merge at **≥ 4 files** inside a window, a window is closed when newest data time > window end + one smallest window, flush always splits at the smallest window edge (tombstones cut per window too), late files into a merged big window are merged at ~10% of its size or daily. Rule 2 for tombstones. (Walkthrough example uses scaled-down 1 → 2 → 4 min windows, merge at 2.)

### 40. Should we support automatic aggregates over older data (rollups / downsampling), like other TSDBs?
- **Answer:** Prometheus (recording rules), InfluxDB (continuous queries / tasks), TimescaleDB (continuous aggregates) and Graphite (retention rollups) precompute per-bucket summaries. Not required by the brief (query-time aggregation is), the hard part is keeping rollups correct under late points, overwrites and deletes, and the ~3 h benchmark data would not benefit. Design idea that fits our engine: compute rollups **during window move-up compaction** and store them as a rollup block in the **same immutable file** (per series per 5 min: count, sum, min, max). Any late point or delete forces the window to be recompacted, which rebuilds the rollup in the same step, so it can never be stale. Store sum+count (mergeable), not avg; percentiles would need sketches (t-digest). Query uses the rollup only if bucket ≥ rollup resolution, window closed and no extra late files; else raw points.
- **Outcome:** deferred: design doc "what production would add"; possible stretch goal.

### 41. Which open API and engine details are confirmed before TDD starts?
- **Answer:** API: `to` inclusive; `k!=v` matches series without tag `k`; a bad point rejects the whole batch (400 with its index); empty buckets omitted; `agg` without `bucket` = one value for the whole range; DELETE resolves a fixed series-id set at delete time; `metric` optional on `/series` and `DELETE` but DELETE needs a metric or a filter; limits 10,000 series / 5,000,000 points per query → 400. Engine: fully deleted series stay listed by `GET /series`; memtable size estimated at ~100 bytes per entry plus a `max_entries` cap; flush when full **or** when the memtable's oldest window closes; a WAL-count change versus MANIFEST refuses to start. TDD order: pure modules bottom-up (TimeWindow, WAL record, skip list, Bloom, SSTable, MANIFEST, memtable, merge/aggregate, filter, split_by_window, Rule 2), then engine (after the threads/snapshot discussion), then crash tests (after the harness discussion), benchmark last.
- **Outcome:** decision (all proposed defaults accepted).

### 42. Can two different series end up with the same canonical text (series.log key, WAL routing)?
- **Answer:** Yes, if names or values contain separators: tags `{a: "1,b=2"}` and `{a: "1", b: "2"}` both print as `m{a=1,b=2}` and would share one series id. Options: escape `\ , = { }` with a backslash, or reject those characters in the API (400).
- **Outcome:** decision: **escape** (any string still accepted, text stays readable). Tested in `tests/unit/test_series_key.py`.

### 43. Does Rule 2 need to check memtables before dropping a tombstone?
- **Answer:** No. A tombstone inside an SSTable was flushed. Every entry in today's memtables was written after that flush, so its seq is bigger, and Rule 1 only hides points with a smaller seq. So no memtable can hold a point that this tombstone hides. This needs memtables to flush in order (the flush lock already does that). Rule 2 then is: drop a tombstone only if no live table outside the compaction job *may* hold one of its series in its time range (footer min/max + Bloom; a Bloom false positive only keeps it longer, never loses a delete). This covers late files in the same window and the bigger parent window's file.
- **Outcome:** decision: memtable check removed from Rule 2. Tested in `tests/unit/test_rule2.py` (mutation check: a time-only check fails the "surely lacks the series" test).

### 44. An all-time delete (`from=0&to=MAX`): how many tombstone pieces does flush write?
- **Answer:** First version cut the delete into every smallest window it covers: 1970 → today with 1 h windows is ~490,000 delete-only files, and up to i64 max the loop never ends. A delete only matters next to data **older** than it, and older data can only be in this flush's points or in live tables (memtables flush in order, so every earlier memtable is already a table). Future windows need nothing: a later write has a bigger seq and is not hidden.
- **Outcome:** decision: flush cuts each delete only into (a) the smallest windows of its own points and (b) the windows of live tables that overlap it, at that table's own size (one piece for a 1-day file, not 24). A delete-only piece for a bigger window is a delete-only table in that window; compaction treats it like a late file. Example: data only at 10:00 and 11:00 today → 2 pieces instead of ~490,000. Tested in `tests/unit/test_windows.py`. **Correction** of my S2 implementation (same day).

### 45. Threads, locks and snapshots on free-threaded 3.14t
- **Answer:** Threads: HTTP handler pool (plain `def` handlers, so queries run in parallel on real cores), one writer thread per WAL, one flush thread, one compaction thread. Single dict/list operations are safe without the GIL, "read then change" is not, so every multi-step change takes a lock. Three problems found:
  - **D1 out-of-order apply (only with N > 1 WALs):** WAL B can apply seq 11 while WAL A is still fsyncing seq 10; a query snapshotting at 11 misses 10, and the same snapshot later sees it (torn read). Deletes go into several WALs, which makes it worse. With 1 WAL, groups apply in seq order and the problem cannot happen. Fix: a **visible seq** (every seq ≤ V applied; RocksDB's idea). Queries snapshot at V, never at "last handed out"; a writer replies 200 only after V reaches its own seq, so a client always reads its acknowledged write.
  - **D2 memtable swap during in-flight groups:** a group that took its seq must land in the memtable that matches its WAL segment. Fix: shared/exclusive swap lock: writers hold it shared from "take seq" to "applied"; the swap (freeze + new memtable + rotate all WALs) holds it exclusive and waits only for in-flight groups (~one fsync). Every seq in the new memtable is then bigger than every seq in the frozen one (#43 relies on this). Writer-preferring, so a write load cannot starve a flush.
  - **D3 one background thread:** a long move-up compaction (a whole day) would block flush, the memtable would fill and writes stall. Fix: separate flush and compaction threads (they meet only at `VersionSet.install`). Backpressure: at most 1 frozen memtable waits for flush; if the active one is full too, writers wait. A slow disk slows writes instead of using unbounded memory.
  - Is N > 1 WALs needed? With group commit, 1 WAL at ~2 ms per fsync covers 100K points/s with ~200 points per fsync (estimate, not measured).
- **Outcome:** decision: **default `wal_count = 1`**; D1 (visible seq, ~20 lines; with N = 1 it equals the last applied seq) kept as a safety net for N > 1; D2 and D3 as above; `max_immutable_memtables = 1`. Benchmark measures 1 vs 2 vs 4 WALs before any default change.

### 46. In which order must series.log and the WAL be fsynced?
- **Answer:** series.log FIRST. If the WAL fsync lands but series.log does not: after a crash series.log knows ids 1–6 while the WAL holds a record for id 7; a new series then gets id 7, and after a second crash replay would put the old orphan record into the new series 7. With series.log synced before the WAL fsync of the same group, a durable WAL record never names an unknown id. The WAL writer calls `catalog.sync()` right before its own fsync; one extra fsync only when the group created a new series.
- Also decided while building it: series.log records are `id u32 | JSON [metric, [[k, v], ...]]` inside the WAL frame (no un-escape parser needed); a cut tail is truncated before new appends (else new records hide behind garbage); a failed fsync fails the group and every later write and is never retried; a delete spanning several WALs is split so each copy names only its own WAL's series (each copy gets that WAL's seq, which is all Rule 1 needs since a series lives in one WAL).
- **Outcome:** decision (series.log fsync before WAL fsync). Tested in `test_wal_writer.py`, `test_series_catalog.py`, `test_wal_set.py`.

### 47. Flush and compaction run on two threads: who owns the MANIFEST?
- **Answer:** Both do "read state → change → commit MANIFEST → install Version". If each kept its own copy, a compaction commit built from an older state could overwrite a flush commit, and the flushed file would vanish from the MANIFEST (data still on disk, but not live, so lost after the WAL segment is deleted). Same for file numbers: two threads could pick the same number.
- **Outcome:** decision: one `LiveState` object owns the current MANIFEST state, file-number allocation, the WAL segment counter and Version building, all under one lock. Flush and compaction only send it an `Edit` (tables added / removed, memtable flushed, next WAL segment). Order inside: new state → `manifest.commit` → `versions.install`. Found while writing the flush tests (#45 D3 consequence).

### Tooling
- A prototype dump tool (outside this repo) printed SSTable / WAL / series.log / MANIFEST files as text (`--hex` for raw bytes) and showed a cut WAL record as "replay stops here". The engine ships the same as `tsdb-dump` (`src/tsdb/tools/dump.py`).

---

## Open topics (not yet discussed)
- Tombstone lifetime details · compaction strategy (size-tiered vs leveled) · snapshot mechanism for readers during compaction · fault-injection mechanism for the 5 crash points · language choice.
