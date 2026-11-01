# Question 2: Design Q&A log

Questions raised while designing the agent, with the answer we settled on.
Kept for the submission (design doc appendix / interview prep). Newest at the bottom.

Legend. **Outcome:** `decision` (changed the design) · `clarified` (no design change) · `deferred` (design doc / later)

---

## Stack

### 1. Same Python as Q1 (free-threaded 3.14t)?
- **Answer:** No. Q2 is network-bound and sequential, so it gains nothing from no-GIL threads. Each question has its own lockfile and Dockerfile, so different versions are fine.
- **Correction (checked on PyPI):** the first reason given was "`onnxruntime` has no 3.14t build". Wrong: `onnxruntime` 1.31.1 ships cp314t wheels. The real blocker is `fastembed`'s dependency `py-rust-stemmers` 0.1.8, which has no cp314t wheel, so it would need a Rust toolchain to build from source.
- **Outcome:** decision. Python 3.13 (regular build) + uv + Docker.

### 2. What are embeddings, and local or paid API?
- **Answer:** An embedding turns text into a list of numbers so texts with similar meaning are close ("refund" ≈ "money back"). Local `bge-small` is free, offline, and gives the same output every run; quality is enough for ~15 notes. Anthropic has no embeddings API; Voyage/OpenAI would add a key and network dependency.
- **Outcome:** decision. `bge-small` via `fastembed`; fake embedder for offline tests.

### 3. Which chat model, and is there a free option?
- **Answer:** Anthropic has no free API tier (a claude.ai subscription does not include API credits). Free options: Ollama (local, weaker at multi-step and injection resistance), Gemini free tier (good tool calling, rate limits, prompts may be used for training; acceptable since all data is fictional), Groq (rate limits). Creating an Anthropic key was blocked in the console.
- **Outcome:** decision. Gemini Flash via a free AI Studio key. Ollama is the fallback if rate limits bite.

### 4. Can we switch models later?
- **Answer:** Yes. The loop only knows our own types (`Message`, `ToolSpec`, `ToolCall`, `ModelReply`) and a `ModelClient` port. Each provider is one adapter; `MODEL_PROVIDER` / `MODEL_NAME` pick it. Cost uses a per-model price table so the cap works for every provider. A shared contract test suite runs against every adapter.
- **Outcome:** decision.

## Data source and write action

### 5. CI workflow runs as a data source?
- **Answer:** CI is not possible for us, and the brief does not require it. Issues, PRs, comments and labels are enough for multi-step questions. (Considered: fake CI via the commit status API; rejected as staged and extra setup.)
- **Outcome:** decision. No CI reads.

### 6. Which repo does the agent read and write?
- **Answer:** A new private sandbox repo, seeded by a script so eval answers are fixed. Fine-grained token for that repo only (Issues RW, Pull requests R, Contents R, Metadata R). Code also enforces a write-repo allowlist, so even an approved write cannot touch another repo.
- **Outcome:** decision.

### 7. Which tools?
- **Answer:** `search_notes`, `list_issues`, `get_issue`, `list_pulls`, `get_pull`, and the one gated write `post_issue_comment`. Small enough to test fully, enough for multi-step questions.
- **Outcome:** decision.

## Safety

### 8. Where does approval come from, and what is it bound to?
- **Answer:** Only from the approver (terminal, or fake approver in tests); never from model text, notes or tool output. Bound to a hash of tool name + canonical args, single-use. Injection safety is structural, not prompt-based.
- **Outcome:** decision.

### 9. How do we flag injections?
- **Answer:** Wrap all notes and tool output as `<data>…</data>`; a pattern check flags suspicious content in the trace.
- **Outcome:** decision.

### 10. Stop conditions?
- **Answer:** 10 steps, `MAX_COST_USD=5`, per-step timeout, same tool + args 3 times → stop.
- **Outcome:** decision.

### 11. Conversation memory?
- **Answer:** Last N turns; old tool results shrunk to one line first. Loses details from old turns.
- **Outcome:** decision.

## Retrieval

### 12. What are BM25, vectors and RRF?
- **Answer:** BM25 = keyword search (rare words weigh more, long docs not over-rewarded); good for exact codes like E4012. Vectors = meaning search via embeddings; good for paraphrases. RRF merges the two rankings by rank only: `Σ 1/(60 + rank)`, so a chunk ranked well by both rises to the top.
- **Outcome:** clarified.

### 13. Search design?
- **Answer:** Heading-aware chunker (~300 tokens, 50 overlap, id `file#n`), note date on every chunk, own BM25 (k1=1.5, b=0.75), brute-force cosine in numpy, RRF k=60, on-disk vector cache keyed by corpus hash, `no_relevant_results` below a score threshold.
- **Outcome:** decision.

## Corpus and evaluation

### 14. What corpus?
- **Answer:** "Ledgerly", a fictional payments API team. 15 notes with the four traps (contradiction, multi-doc, injection, unanswerable); the sandbox repo describes the same world, plus one injected issue comment.
- **Outcome:** decision.

### 15. Golden set and scoring?
- **Answer:** 25 questions across search, tool use, multi-step, contradiction, adversarial, unanswerable, write-with-approval. Rule-based scoring (no LLM judge); recall@5, tool-call accuracy, task success; temperature 0 + fixed seed; raw results committed.
- **Outcome:** decision. Experiment: BM25 vs vector vs hybrid.
