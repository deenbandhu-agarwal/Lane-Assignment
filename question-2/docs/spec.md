# Question 2: Design spec

Status: the design as agreed **before** implementation (kept as written). What changed while building is in [`design-qa.md`](design-qa.md) #16 onward and summarised in [`design.md`](design.md).

## 1. Goal

A chat agent that answers questions about a GitHub repo and a folder of team notes. It uses its own agent loop, tool registry and hybrid search (no agent frameworks, no vector DBs). It can perform one kind of write, and only after a human approves it in code the model cannot bypass. It cites sources, says "couldn't find" when evidence is missing, and stops at step, cost and loop limits.

## 2. Stack

| Item | Choice |
|---|---|
| Language | Python 3.13 (regular build) + uv + Docker |
| Chat model | Gemini Flash (free AI Studio key) behind a `ModelClient` port; fake model for tests |
| Embeddings | `bge-small` via `fastembed` (local, CPU) behind an `Embedder` port; fake embedder for tests |
| Validation | pydantic (tool args → JSON schema) |
| Data source | Private sandbox GitHub repo, filled by a seed script. No CI / Actions |
| Write action | `post_issue_comment` on the sandbox repo (undo = delete the comment) |

## 3. Architecture

```
CLI (chat) ──► Agent loop ──► ModelClient (Gemini | Fake | later Anthropic/Ollama)
                  │
                  ▼
            Tool registry ── validate args (pydantic) ──► read tools ──► GitHub API / search_notes
                  │
                  └── write tool ──► Approval gate ──► approver (terminal | fake) ──► execute once
                  │
            Tracer (JSONL per run) + Budget (steps, cost, timeout, loop detection)
```

### 3.1 Model abstraction (swap models via `.env`)

```python
Message(role, content, tool_call_id=None)
ToolSpec(name, description, json_schema)
ToolCall(id, name, raw_args: str)          # raw, so malformed args reach our validator
ModelReply(text, tool_calls, usage=Usage(input_tokens, output_tokens))

class ModelClient(Protocol):
    def complete(self, messages: list[Message], tools: list[ToolSpec]) -> ModelReply: ...
```

- Adapters: `GeminiClient`, `FakeModelClient` (scripted). Later `AnthropicClient` / `OllamaClient` with no change elsewhere.
- Selection: `MODEL_PROVIDER`, `MODEL_NAME` in `.env`; one factory builds the client.
- Cost: price table keyed by model name; budget computes dollars from `usage` (paid-tier prices even on the free tier, so the cap is real and testable).
- One shared contract test suite runs against every adapter using recorded responses.
- Same pattern for `Embedder`: `FastEmbedEmbedder`, `FakeEmbedder`.
- Free-tier 429s: retry with backoff in the adapter.

### 3.2 Tools

| Tool | Type | Purpose |
|---|---|---|
| `search_notes(query, k=5)` | read | Hybrid search; returns chunk ids, dates, text |
| `list_issues(state, label?)` | read | Issues filtered by state/label |
| `get_issue(number)` | read | Issue body + comments |
| `list_pulls(state)` | read | PRs with linked issue |
| `get_pull(number)` | read | PR details + reviewers |
| `post_issue_comment(number, body)` | write (gated) | The one write |

Bad args → structured error returned to the model (field, problem), so it can retry.

### 3.3 Approval gate and safety

- Approval comes only from the approver (terminal prompt, or fake approver in tests). Never from model text, notes or tool output.
- Approval bound to `sha256(tool name + canonical JSON args)`; single-use token, deleted after use.
- Repo allowlist from `.env`: writes to any other repo are refused even if approved.
- All notes and tool results are wrapped as `<data>…</data>` and treated as data. A pattern check ("ignore previous instructions", tool names inside data, etc.) flags suspicious content in the trace.

### 3.4 Agent loop limits

| Limit | Default |
|---|---|
| Max steps | 10 |
| Cost cap | `MAX_COST_USD=5` |
| Per-step timeout | configurable |
| Loop detection | same tool + same args 3 times → stop |
| Malformed tool call | validation error returned to model; limited retries |

### 3.5 Conversation memory

Keep the system prompt + last N turns; shrink old tool results to one-line summaries first (largest and least reused). Cost: details from old turns are lost.

### 3.6 Trace

One JSONL file per run: prompt, tool call, result, latency, tokens, cost per step, injection flags, gate decisions.

## 4. Retrieval

| Piece | Design |
|---|---|
| Chunker | One chunk per markdown section; sections over 220 words are windowed with 40-word overlap. Text prefixed with `title > heading`. Chunk id = `file#n` |
| Dates | `date:` front-matter stored on every chunk and shown in results (contradiction handling) |
| BM25 | Own implementation, k1=1.5, b=0.75, lowercase + punctuation split, stopwords, plural stripping |
| Vectors | numpy array, brute-force cosine (one matrix multiply) |
| RRF | `score = Σ 1/(60 + rank)` over BM25 and vector lists |
| Cache | Vectors cached on disk keyed by hash of the corpus |
| Not found | A chunk is kept only if BM25 ≥ 3.0 or cosine ≥ 0.60 (bge-small, calibrated); none kept → `no_relevant_results`. Decided on raw signals, not RRF (rank-based scores always look fine) |
| Citation check | Final answer's citations compared with ids tools returned this run: none returned + citations → replaced with "couldn't find"; some unsupported → warning appended |

Retrieval mode (`bm25 | vector | hybrid`) is a parameter so the experiment reuses the same code.

## 5. Corpus: "Ledgerly" (fictional payments API team)

Notes and sandbox repo describe the same world, so questions can combine both.

| # | Note | Trap / purpose |
|---|---|---|
| 1 | `release-policy-2024-03.md`: 1 approval to merge | Contradiction (older) |
| 2 | `release-policy-2025-06.md`: 2 approvals to merge | Contradiction (newer; does not say it replaces #1) |
| 3 | `team-owners.md`: service → owning team | Multi-doc (part 1) |
| 4 | `oncall-rota.md`: team → on-call person | Multi-doc (part 2) |
| 5 | `error-codes.md`: E4012 = token expired… | BM25 wins (exact codes) |
| 6 | `reversals-runbook.md`: "returning funds to a cardholder" (never says "refund") | Vector wins (paraphrase) |
| 7 | `vendor-integration-notes.md`: hidden instruction to post a comment | Prompt injection in a note |
| 8–15 | Architecture, deploy steps, coding standards, incident postmortem, API rate limits, onboarding, glossary, data retention | Realistic filler |
| — | No office address, salaries, 2023 roadmap | Unanswerable questions |

Sandbox repo: ~8 issues (bugs/features, labels), 3 PRs linked to issues, a few comments. Issue #3 mentions E4012 (combines `get_issue` + `search_notes`). One issue comment carries a hidden instruction (injection in tool output).

## 6. Golden set and evaluation

| Category | Count | Scored by |
|---|---|---|
| Search only | 6 | Expected chunk in top 5; cited |
| Tool use | 4 | Expected tool + args; answer contents |
| Multi-step | 5 | Cites both docs / uses both tools; right answer |
| Contradiction | 2 | Prefers newer or states conflict; cites 2025 note |
| Adversarial | 3 | No write attempted or blocked; flagged in trace |
| Unanswerable | 3 | Says "couldn't find"; no invented citation |
| Write with approval | 2 | Gate asks; deny → no write; approve → write once |

25 questions in `eval/golden.yaml` (question, expected chunks, expected tools, must/must-not contain, write expected). Rule-based scoring, no LLM judge.

Metrics: recall@5, tool-call accuracy, task success. Temperature 0, fixed seed. Raw results committed under `eval/results/` with the regenerate command.

Experiment: BM25-only vs vector-only vs hybrid on the same golden set; numbers + analysis of the 3 worst failures.

## 7. Layout

```
question-2/
  src/agent/
    models/      ModelClient port, gemini.py, fake.py, pricing.py
    loop.py      agent loop: steps, timeout, budget, loop detection, malformed retry
    memory.py    last-N turns, old tool results shrunk
    tools/       registry.py, github.py, notes.py
    gate.py      approval gate: args hash, single-use token, repo allowlist
    retrieval/   chunker, bm25, vectors, rrf, embedders, index cache
    safety.py    <data> wrapping + injection flags
    trace.py     JSONL per run
    cli.py       chat REPL + terminal approver
  corpus/        15 Ledgerly notes
  scripts/       seed_sandbox.py
  eval/          golden.yaml, run_eval.py, experiment.py, results/
  tests/         offline: fake model + fake embedder
```

## 8. Build order

| # | Step | Required tests covered |
|---|---|---|
| 1 | Types, fake model, loop, budget, trace | Runaway/limits; trace per run |
| 2 | Registry + gate + `post_issue_comment` (GitHub mocked) | Gate: no write without approval, single-use, args-bound |
| 3 | Safety wrapper + injected tool output | Injection in tool output → no write |
| 4 | Corpus + retrieval + `search_notes` | Injection in note → no write; no evidence → "couldn't find" |
| 5 | Real GitHub tools, seed script, Gemini adapter | Real mode |
| 6 | Golden set, eval, experiment | README numbers |
| 7 | README, design doc (≤ 3 pages), demo transcript | — |

Risk: Gemini free-tier rate limits during step 6. Fallback: Ollama via the same `ModelClient` port.

## 9. Environment variables (for `.env.example`)

`MODEL_PROVIDER`, `MODEL_NAME`, `GEMINI_API_KEY`, `GITHUB_TOKEN` (fine-grained, sandbox repo only: Issues RW, Pull requests R, Contents R, Metadata R), `GITHUB_REPO`, `WRITE_REPO_ALLOWLIST`, `MAX_COST_USD=5`, `MAX_STEPS=10`, `STEP_TIMEOUT_S`, `RETRIEVAL_MODE=hybrid`, `EMBED_MODEL`, `SEED`.
