# Question 1 — Query Catalog (API contract, draft)

Status: **decided** (2026-11-01). Items marked ⚑ were open; the decisions are in the table at the end.

---

## 1. Filter language (shared by `/query`, `/series`, `DELETE /series`)

```
expr    := and_expr ( "OR" and_expr )*
and_expr:= factor   ( "AND" factor )*
factor  := "(" expr ")" | matcher
matcher := KEY "=" VALUE | KEY "!=" VALUE
```

- Precedence: `AND` binds tighter than `OR`; parens override. Keywords case-insensitive.
- KEY/VALUE: `[A-Za-z0-9_.\-:/]+`, or double-quoted for anything else (spaces, `=`, parens) ⚑
- Empty / missing filter = **all series** of the metric.
- `k=v` → posting list `k=v`.
- `k!=v` → `universe − posting(k=v)`. **Series without tag `k` match** (Prometheus semantics) ⚑
  - `universe` = all series of the metric (from `metric` posting list) — set op, not a scan.
- Evaluation: AND → intersect starting from the smallest list; OR → union.

| # | Filter | Meaning |
|---|---|---|
| F1 | `service=api` | single matcher |
| F2 | `region=us-east OR region=us-west` | union |
| F3 | `region=us-east AND service=api` | intersection |
| F4 | `(region=us-east OR region=us-west) AND service=api` | brief's example |
| F5 | `(a=1 OR a=2) AND b!=3` | brief's example, negation |
| F6 | `host!=h1` | negation only → `universe − {host=h1}` |
| F7 | `env="prod east"` | quoted value ⚑ |
| F8 | *(empty)* | all series of metric |

---

## 2. `POST /write`

```json
POST /write
[ {"metric":"cpu","tags":{"host":"h1","region":"us-east"},"timestamp":1730000000000,"value":0.42}, ... ]
```

| Case | Response |
|---|---|
| All valid | `200 {"written": N}` — only after WAL durability rule is met |
| Any point invalid | `400 {"error": ..., "detail": {"index": i}}` — **whole batch rejected** (atomic) ⚑ |
| Same series + ts written twice | Accepted; **last write wins** (higher sequence number) |
| Empty batch | `400` ⚑ |

Validation: `metric` non-empty string; `tags` object of string→string (may be empty ⚑); `timestamp` integer ms ≥ 0; `value` finite float64 (NaN/±Inf rejected ⚑); batch ≤ N points (e.g. 10K) ⚑.
Series id = `metric` + sorted tags (order of tags in JSON doesn't matter).

---

## 3. `GET /query`

| Param | Required | Example | Notes |
|---|---|---|---|
| `metric` | yes | `cpu` | |
| `filter` | no | `(region=us-east OR region=us-west) AND service=api` | URL-encoded |
| `from` | yes | `1730000000000` | ms, **inclusive** |
| `to` | yes | `1730003600000` | ms, **inclusive** (brief says `[from, to]`) ⚑ |
| `agg` | no | `avg` | `avg|sum|min|max|count` |
| `bucket` | iff `agg` | `5m` | `<int>(ms|s|m|h|d)`; `agg` without `bucket` = one bucket for whole range ⚑ |

Results are **per series** (no cross-series rollup — that's a "cut" ⚑).

**Raw response**
```json
{"series":[{"metric":"cpu","tags":{"host":"h1","region":"us-east"},
            "points":[[1730000000000,0.42],[1730000010000,0.43]]}]}
```

**Aggregated response** — bucket start = `ts - (ts mod bucket)` (epoch-aligned); empty buckets omitted ⚑
```json
{"series":[{"metric":"cpu","tags":{...},"agg":"avg","bucket_ms":300000,
            "buckets":[[1730000100000,0.425],[1730000400000,0.51]]}]}
```

| # | Query | What it proves |
|---|---|---|
| Q1 | `metric=cpu&filter=host=h1&from&to` | raw single series, sorted by ts |
| Q2 | F2/F3/F4/F5 filters | set-op evaluation |
| Q3 | `agg=avg|sum|min|max|count&bucket=1m` | each aggregate |
| Q4 | `bucket=1h` with `from` not on a boundary | buckets still epoch-aligned (first bucket may start before `from`, contains only in-range points) |
| Q5 | point exactly at `from` and at `to` | boundary inclusivity |
| Q6 | ts written twice, then query | returns latest value only, once |
| Q7 | query after delete (memtable, SSTable, post-compaction, post-restart) | tombstones mask data |
| Q8 | query spanning memtable + L0 + L1 | merge-on-read |
| Q9 | filter matches nothing / unknown metric | `200 {"series": []}` |
| Q10 | `count` on a range with overwrites | counts unique timestamps, not raw writes |

Error body is always `{"error": text, "detail": {...}}` (`detail` only when there is something to point at: `index` of a bad point, `position` in a filter). Errors (`400`): missing `metric`/`from`/`to`; `from > to`; bad filter syntax (with position); unknown `agg`; bad `bucket`; `agg` without `bucket` (if we choose to require it) ⚑. Result-size guard: max points/buckets per response → `400`/`413` ⚑.

---

## 4. `GET /series`

| Param | Required | Notes |
|---|---|---|
| `metric` | no ⚑ | if absent, universe = all series of all metrics |
| `filter` | no | same grammar |

```json
{"series":[{"metric":"cpu","tags":{"host":"h1","region":"us-east"}}, ...]}
```

| # | Case | Expected |
|---|---|---|
| S1 | F4 filter | matching series, sorted deterministically |
| S2 | series whose **all** points were deleted | ⚑ still listed (tombstone is time-ranged) vs hidden — propose: still listed unless delete covered all time |
| S3 | no match | `200 {"series": []}` |

Served purely from the inverted index — no data-block reads.

---

## 5. `DELETE /series`

| Param | Required | Notes |
|---|---|---|
| `metric` | ⚑ | |
| `filter` | ⚑ | at least one of `metric`/`filter` required — no "delete everything" by accident |
| `from`, `to` | yes ⚑ | inclusive; allow `from=0&to=MAX` for "all time" |

Response: `200 {"deleted_series": K}` (count of series the tombstone applies to; points not counted — too expensive) ⚑

| # | Case | Expected |
|---|---|---|
| D1 | delete range in memtable | gone from query |
| D2 | delete range already in SSTables | tombstone masks it |
| D3 | D2 then compaction (repeated) | still gone; data physically dropped |
| D4 | D2 then kill -9 + restart | still gone (tombstone is in WAL) |
| D5 | write **after** delete into same range | new point **visible** (seq > tombstone seq) |
| D6 | delete with `!=` filter | resolves series set at delete time ⚑ (vs. stored predicate) |

---

## 6. Open decisions (⚑) to close

1. `to` inclusive or exclusive?
2. `!=` matches series missing the key?
3. Whole-batch reject vs partial accept on `/write`?
4. Empty buckets: omit vs return null?
5. `agg` without `bucket`: whole-range single value, or 400?
6. Tombstone = resolved series-id set + range, or stored filter predicate? (affects D6 and future series)
7. Is `metric` required on `/series` and `DELETE`?
8. Response size limits.

### Decisions for the ⚑ items (confirmed)

| # | Decision | Proposed |
|---|---|---|
| 1 | `to` inclusive? | Inclusive (the brief writes `[from, to]`) |
| 2 | `k!=v` matches series without tag `k`? | Yes (Prometheus semantics, pure set difference) |
| 3 | `/write` with one bad point | Reject the whole batch |
| 4 | Empty buckets | Omitted |
| 5 | `agg` without `bucket` | One value for the whole range |
| 6 | Tombstone form | Fixed series-id set + time range (resolved at delete time) |
| 7 | `metric` on `/series` and `DELETE` | Optional; `DELETE` needs a metric or a filter |
| 8 | Response size | Max 10,000 series and 5,000,000 points per query → 400 |
| 9 | `GET /series` for a series whose points are all deleted | Still listed (the series exists; its data is gone) |
