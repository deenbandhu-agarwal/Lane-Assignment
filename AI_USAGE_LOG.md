# AI Usage Log

Covers both questions.

## Tools and what they were used for

| Tool | Question | Used for |
|---|---|---|
| Claude Code (Claude Opus) | Q1 | **Design discussion:** 55 recorded questions, each with the answer and the outcome ([`question-1/docs/design-qa.md`](question-1/docs/design-qa.md)). **Learning:** worked examples with real bytes and an animated walkthrough page, kept private (outside the repo). **Code:** scaffold with interfaces and DI, then the engine test-first: for each module I approved the test seams, the AI wrote the failing test, then the code, then a commit. **Testing:** crash harness, snapshot stress test, mutation checks (break the engine on purpose, confirm a test fails). **Measuring:** benchmark, Docker run, fsync timing. **Writing:** first drafts of the README and DESIGN.md |
| Skill for Claude Code (mattpocock/skills `tdd`) | Q1 | The red → green loop, and agreeing the test seams before writing tests |
| Claude Code | Q2 | _TBD_ |

## Cases where AI output was wrong or risky, and how they were caught

**Q1-1. A race in the AI-written skip list gave torn reads.** All unit tests passed. The snapshot
stress test (1 writer, 3 readers, flushes and compactions every few ms) then showed a batch on
9 of 10 series. The AI's first idea (memory reordering on ARM) was tested and was wrong. Re-running
the same query on the same snapshot gave the right answer, which pointed at the read code: `iter_from`
read a node's `next` twice, and in between the writer linked a smaller key there. Fixed by stepping
over smaller keys; a new test fails in under a second without the fix. The same hunt found a second
bug: series ids were looked up before the snapshot was taken (`design-qa.md` #52).
*Lesson: green unit tests said nothing about concurrency; only a test built to find torn reads did.*

**Q1-2. Benchmark numbers that were not real.** The first benchmark showed 315 K points/s with an
fsync before every reply. That was too fast for a real disk flush. Measured: `os.fsync` on macOS
took 0.03 ms because it stops at the drive's cache; `F_FULLFSYNC` takes 3.7 ms. The numbers were
thrown away and the engine now uses `F_FULLFSYNC` on macOS (#53). The AI's earlier estimate that one
WAL "covers ~100 K points/s" was also too high (measured ~70 K, #54), and the README first said a
memtable holds 2 M entries when the 64 MB limit stops it at ~671 K.
*Lesson: every performance claim is now a measurement with its method written next to it.*

**Q1-3. Complexity designed before it was measured.** The AI designed N WAL files with per-series
routing, a shared/exclusive swap lock and an out-of-order "visible seq" (#15–#18, #45). It was built
and tested. The benchmark then showed more WALs were slower (1 / 2 / 4 WALs ≈ 70 K / 52 K / 28 K
points/s: the fsyncs do not run in parallel on this disk, and all WALs feed one memtable). I asked
to remove it: ~330 lines of code and tests went (#55).
*Lesson: measure the simple version first.*

Smaller ones, caught in review: the first scaffold had no dependency injection (each class built its
own collaborators), so swapping the skip list was not a one-line change; a test now enforces it.
The first worked example overwrote a memtable value in place, which breaks snapshot reads (#9).

## What I did not delegate

- **The decisions.** Every option was argued in the Q&A log and I chose: skip list, fsync before
  200 with group commit, per-table Bloom filter, time-window compaction with always-split flush,
  Python 3.14t over Go (I must explain and change the code live), removing multi-WAL.
- **The challenge questions** that changed the design: keep versions in the memtable, SOLID and DI,
  multiple WALs, read cost across many series, tombstone memory, flush splitting at window edges.
- **The test seams.** I approved the seams for every module before any test was written, and each
  green step was committed separately, so the history shows the order.
- **Checking the numbers.** Benchmarks were re-run on a quiet machine and in Docker before they went
  into the README.
