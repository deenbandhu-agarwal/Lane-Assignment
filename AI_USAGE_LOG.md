# AI Usage Log

Covers both questions.

## Tools and what they were used for

| Tool | Q | Used for |
|---|---|---|
| Claude Code (Claude Opus) | Q1 | **Design:** 55 recorded questions with answers ([`design-qa.md`](question-1/docs/design-qa.md)). **Learning:** worked byte-level examples and an animated walkthrough (kept outside the repo). **Code:** scaffold with interfaces and DI, then test-first per module (I approved the seams; the AI wrote the failing test, then the code, then committed). **Testing:** crash harness, snapshot stress test, mutation checks. **Measuring:** benchmark, Docker, fsync timing. **Writing:** first drafts of the README and DESIGN.md |
| Skill for Claude Code (mattpocock/skills `tdd`) | Q1 | Red → green loop; agreeing test seams first |
| Claude Code (Claude Opus) | Q2 | **Explaining:** the brief, BM25 / vectors / RRF, embeddings, free model options; 29 recorded questions ([`design-qa.md`](question-2/docs/design-qa.md)). **Code:** 5 build steps from an agreed spec, each with offline tests and a commit. **Data:** first drafts of the 15 notes, seed data, 25 golden questions. **Running:** sandbox seeding, 4 eval runs, the retrieval experiment, reading traces. **Writing:** first drafts of the README, design doc, experiment write-up |

## Cases where AI output was wrong or risky, and how they were caught

**Q1-1. Torn reads from a race in the AI-written skip list.** All unit tests passed. The snapshot
stress test showed a batch on 9 of 10 series. The AI's first idea (ARM memory reordering) was tested
and wrong. The same query on the same snapshot was right on re-run, which pointed at the read code:
`iter_from` read `next` twice while the writer linked a smaller key in between. Fixed, with a test
that fails in under a second without the fix. The same hunt found ids looked up before the snapshot
(#52). *Lesson: green unit tests say nothing about concurrency.*

**Q1-2. Benchmark numbers that were not real.** 315 K points/s with an fsync per reply was too fast.
`os.fsync` on macOS took 0.03 ms (stops at the drive cache); `F_FULLFSYNC` takes 3.7 ms. The numbers
were thrown away and the engine uses `F_FULLFSYNC` (#53). Also too high: "one WAL covers ~100 K/s"
(measured ~70 K, #54) and "a memtable holds 2 M entries" (64 MB stops it at ~671 K).
*Lesson: every performance claim is a measurement with its method next to it.*

**Q1-3. Complexity designed before it was measured.** The AI designed N WALs with per-series routing,
a swap lock and an out-of-order visible seq (#15–#18, #45). Built and tested, then benchmarked:
1 / 2 / 4 WALs ≈ 70 K / 52 K / 28 K points/s (fsyncs don't parallelise on this disk; all WALs feed one
memtable). I had it removed: ~330 lines (#55). *Lesson: measure the simple version first.*

**Q2-1. The eval harness, not the agent, failed half the first run.** Run 1 scored 12/25. In the
AI-written `golden.yaml` an unquoted ` #3` starts a YAML comment, so 6 questions reached the model
cut off ("What is issue"). Two correct answers failed on Unicode (U+202F inside a name, `【…】`
citations). Fixed by quoting, a loader check for truncated questions and normalising before scoring;
run 1 stays in the repo, labelled buggy (#25). *Lesson: validate the eval's inputs, not just outputs.*

**Q2-2. A citation check that was too strict, found only in a live demo.** The check (cite only ids
a tool returned) passed every test. In the demo the agent answered a follow-up from a note fetched one
question earlier, and the check flagged a correct citation: it only counted the current question.
Memory now carries citable ids from turns it holds in full (#28). *Lesson: per-run tests miss
multi-turn behaviour.*

**Q2-3. A retry that could never succeed.** Groq rejected an answer (`output_parse_failed`); the AI's
retry failed 4 times the same way, because temperature 0 + a fixed seed reproduces the same bad
output. Retries now re-sample at 0.7 without the seed (my call); the README states that such a run
is not exactly repeatable (#26).

**Smaller, caught in review.** Q1: the first scaffold had no DI, so swapping the skip list was not a
one-line change (a test now enforces it); the first worked example overwrote a memtable value in
place, which breaks snapshot reads (#9). Q2: "`onnxruntime` has no 3.14t build" was wrong; PyPI
showed the blocker is `py-rust-stemmers` (#1). GitHub Models was assumed to work but answered every
call with "OK", so the eval moved to Groq (#24). The injection detector flagged the agent's own
unknown-tool error, which lists the write tool (#27).

## What I did not delegate

- **Decisions.** Q1: skip list, fsync before 200 with group commit, per-table Bloom filter,
  time-window compaction with always-split flush, Python 3.14t over Go (I must explain and change it
  live), removing multi-WAL. Q2: Gemini then Groq over paid APIs, local embeddings, a private sandbox
  repo with no CI, Python 3.13, the six tools, the search design, the golden set, a model abstraction
  swappable by config (proved by Gemini → Groq with no loop change), the warmer retry.
- **The challenge questions** that changed Q1's design: versions in the memtable, SOLID and DI,
  multiple WALs, read cost across many series, tombstone memory, flush splitting at window edges.
- **Test seams.** Approved per module before any test; each green step committed separately.
- **Scope of the repo.** Ideas were brainstormed in chat and written to files only after I agreed;
  the brief and my notes stay outside the repo.
- **Credentials.** I created the sandbox-scoped GitHub token and model keys; secrets live only in a
  git-ignored `.env`.
- **Checking the numbers.** Benchmarks re-run on a quiet machine and in Docker before the README.
