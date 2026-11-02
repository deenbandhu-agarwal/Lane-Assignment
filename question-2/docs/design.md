# Design: Ledgerly agent

The design bet is that **safety lives in code the model cannot reach; the model is trusted
only to be useful.** Every safety property must hold when the model is hostile, and the tests
prove it with a fake model that obeys injected instructions.

## 1. Architecture

```
              ┌──────────────────────── Agent loop (loop.py) ────────────────────────┐
user ──► CLI ─┤ Budget: steps · cost-before-call · per-step timeout · repeat · malformed │──► answer
              │        │                                    ▲                          │   + citation check
              │        ▼                                    │ <data source=…> wrapped   │
              │  ModelClient port ──► Fake | Gemini | OpenAI-compatible (Groq, Ollama…) │
              │        │ tool calls (raw JSON args)                                     │
              │        ▼                                                                │
              │  ToolRegistry ── pydantic validate ──► structured error back to model   │
              │        ├── reads: search_notes · list/get_issue · list/get_pull         │
              │        └── write: post_issue_comment ──► ApprovalGate ──► Approver      │
              │                                         (sha256 args, 1-use token)  (human y/N)
              │                                         ──► repo allowlist ──► GitHub   │
              └────────────── Tracer: one JSONL per run (every step, every decision) ───┘
search_notes: chunker → BM25 ┐
                     vectors ┴► floors on raw scores ► RRF(k=60) ► top 5 with chunk id + note date
```

| Piece | Choice | Why |
|---|---|---|
| Model port | Our own `Message/ToolCall/ModelReply` types. One adapter per provider, plus a shared contract test | Switching Gemini → Groq needed no change to the loop. Raw args stay raw, so *our* validator sees malformed calls. |
| Tool registry | pydantic models (`extra="forbid"`) → JSON schema for the model. Errors are returned to the model as `{type, field, problem}` | The model can fix its own mistakes. After 3 malformed steps in a row, the run stops. |
| Approval gate | The token is bound to `sha256(tool + canonical args)`, is single-use and is burned on any use. The approver is a separate object (a terminal prompt that defaults to No) | Nothing in the conversation can produce a token. Approving A cannot authorise B. |
| Injection handling | All data is wrapped in `<data>`; a regex detector flags it in the trace and on the wrapper | The *gate* is the defence. Flags are for observability, so a missed pattern costs visibility, not safety. |
| Citations | Cited ids are checked against the ids tools returned (this turn, plus turns still in memory in full) | "Invent nothing" is checked in code. A fabricated answer with no evidence is replaced with "couldn't find". |
| Retrieval | A heading-aware chunker (220 words, 40 overlap). Own BM25, numpy cosine, RRF | Brute force over 59 chunks takes microseconds. An index would be complexity with no gain. |
| "Not found" | Decided on *raw* BM25 ≥ 3.0 or cosine ≥ 0.60, never on RRF | RRF scores are rank-only, so the top hit always looks relevant. |
| Trace | JSONL per run: prompt, reply, tool, args, result, latency, tokens, cost, flags, gate decisions, citation check | It is the audit log for every claim in the README. Each eval row links to its trace. |

## 2. Trade-offs

| Decision | Gave up | Got |
|---|---|---|
| **Gate in code, not prompt rules** | Some UX: the model can't say "already approved" | Safety that doesn't depend on model quality. The tests use a model that obeys injections, and nothing is written. |
| **Rule-based eval, no LLM judge** | Partial credit and nuance. One correct answer (t4) fails on strict tool expectations | It is deterministic, free and auditable. Every pass or fail is explainable from the trace. |
| **Local `bge-small` embeddings** | Some quality versus large API embedders | No key, offline, the same vectors every run, and Docker tests with the network disabled |
| **Truncation memory (6 turns, older tool output cut to 300 chars)** | Detail of old tool output | No summariser call per turn, and no summary that quietly changes facts. Re-fetching is cheap. |
| **Hybrid retrieval as the default** | MRR (0.84 vs BM25's 0.93) | recall@5 of 1.00 vs 0.91. The model sees all top 5, so a *missing* chunk hurts, a rank-2 chunk doesn't ([experiment](experiment.md)) |
| **Temperature 0 + seed, but re-sample at 0.7 after a provider parse failure** | Exact repeatability of runs that hit one | Runs that would otherwise crash (u3) finish. First attempts stay deterministic. |
| **Cost checked before each call, from the previous call's cost** | Can overshoot by at most one call | Simple and testable. With unknown output length, a strict pre-check is impossible anyway. |
| **Fixed sandbox repo, seeded by script** | Realism of a live repo | The eval answers are stable, and the write target is owned and reversible |

## 3. What was cut

| Cut | Why | Cost of the cut |
|---|---|---|
| CI / workflow-run reads | No CI on the sandbox, and the brief doesn't require it | Fewer multi-hop question types |
| Claim-level citation checking | Needs claim extraction (another model call or an NLP pipeline) | m3: a correct answer that omits a source passes the checker. Only *wrong* citations are caught. |
| Reranker | Corpus too small to justify it | Exact-match chunks sit at rank 2 under hybrid, not rank 1 |
| Streaming, async, parallel tool calls | Sequential, network-bound, with a single user | Higher latency (~10 s per step, mostly free-tier pacing) |
| An LLM-based injection classifier | Regex flags plus a code gate are enough, because flags are not the defence | Paraphrased injections may go unflagged (but are still not obeyed) |
| Repeated eval runs with confidence intervals | Free-tier quotas | Results are reported as a range across 3 runs (20–21/25), not with statistical bounds |

## 4. Production hardening

| Area | What I would add |
|---|---|
| **Approval** | Show the approver a diff-style preview plus the trace link. Approvals expire (TTL), are tied to the run id and are signed by an identity (SSO) with an audit log. Two-person approval for risky writes. A per-day cap on writes. |
| **Permissions** | A GitHub App with per-installation tokens instead of a personal token. Read and write credentials kept in separate processes, so a bug in a read tool cannot write. The allowlist kept in config with an owner. |
| **Injection** | Keep the code gate as the guarantee. Add a classifier for flagging, quarantine flagged documents from retrieval until reviewed, and strip HTML comments from tool output before the model sees them. |
| **Grounding** | Claim-level citation checks (an NLI or judge pass on each sentence). Reject or annotate uncited claims. A "not found" threshold calibrated on held-out questions. |
| **Retrieval at scale** | Incremental re-indexing, an ANN index once there are ~100k chunks, a reranker, document ACLs enforced at search time (filter before ranking), and freshness or supersession metadata instead of guessing from dates. |
| **Reliability** | A per-provider circuit breaker with fallback to a second model through the same port. Idempotency keys on writes. Retry budgets per run as well as per call. |
| **Cost** | A per-user and per-day budget alongside the per-run cap. Prompt caching for the system prompt and tool schemas. A smaller model for routing, a larger one for answers. |
| **Observability** | Ship traces to a store (OpenTelemetry spans). Dashboards for stop reasons, gate decisions, injection flags, unsupported-citation rate and cost per answer. Alert on writes per hour. |
| **Eval** | Run the golden set in CI on every prompt or model change, several seeds, report confidence intervals, add production questions that failed, and get independent labellers. Validate the eval inputs too (run 1 lost 6 questions to a YAML `#`). |
| **Memory** | Per-user sessions with retention limits, PII scrubbing before traces are stored, and summarisation only with a fact-preservation check. |

## 5. What I learned building it

1. **The harness needs tests as much as the agent.** Run 1's 12/25 was mostly my YAML and
   Unicode handling. The fix was to validate the inputs (questions must not be truncated) and
   normalise outputs before scoring.
2. **Provider quirks only appear in real mode.** Groq's `output_parse_failed` and
   `tool_use_failed` 400s, `【】` citations and narrow no-break spaces were all invisible to mocks.
   Each became an adapter test once it was found.
3. **Deterministic settings are not deterministic.** At temperature 0 with a seed, three runs
   still failed partly different questions. One run is a sample, not a measurement.
