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

## Implementation findings

### 16. How does the agent "invent nothing" if the model ignores the prompt?
- **Answer:** A code check on the final answer. Every citation (`[file.md#n]`, `[issue#n]`, `[pr#n]`) is compared with the ids tools actually returned in this run. If nothing was returned and the answer still cites something, the answer is replaced with "I couldn't find that in the notes or the repo." If some citations are unsupported, a warning is appended. Recorded in the trace.
- **Outcome:** decision. Limit: uncited invented claims are not caught; that is left to the prompt and the eval.

### 17. What did calibrating search with the real model change?
- **Answer:** (a) "approvals" did not match "approval", so the 2024 policy was missed: added plural stripping to BM25. (b) `onboarding.md` said "we have no office", which made the "office address" question answerable: sentence removed. (c) bge-small scores unrelated text at 0.54 to 0.58 cosine, so the relevance floor is 0.60; BM25 floor 3.0. Measured on 8 probe questions, real bge-small, 59 chunks.
- **Outcome:** decision. Thresholds are revisited with the golden set.

### 18. Why is "not relevant" decided on BM25/cosine and not on the fused score?
- **Answer:** RRF scores depend only on rank, so the top hit always gets about 1/61 even when nothing matches. The raw signals say whether anything matched at all.
- **Outcome:** clarified.

### 19. Why does injection detection only look for the write tool's name?
- **Answer:** Looking for every tool name flagged normal output (the `echo` test tool returns a key named `echo`). Only a mention of the write tool inside data is suspicious.
- **Outcome:** decision.

### 20. What are the Gemini free-tier limits, and how does the client cope?
- **Answer:** A real run hit `429 ... generate_content_free_tier_requests, limit: 5, model: gemini-3.6-flash`: the free tier allows **5 requests per minute**, and `gemini-3.5-flash` is counted against `gemini-3.6-flash`'s quota. The public rate-limits page publishes no per-model numbers (only visible in AI Studio), so the daily limit is unknown. The client now paces itself (`MODEL_RPM=5`, 12 s between calls) and on 429 waits the server's suggested delay instead of a fixed backoff.
- **Outcome:** decision. A 25-question eval at ~4 calls per question takes ~20 minutes per run on the free tier; the daily limit may block running it several times (3 retrieval modes).

### 21. Why is gemini-3.5-flash priced at $0.75 / $3.75 per 1M tokens?
- **Answer:** It is not on the pricing page. The 429 shows it is served as gemini-3.6-flash, whose listed standard paid price is $0.75 input / $3.75 output (thinking tokens billed as output), valid through 2026-12-31.
- **Outcome:** decision. Free tier spends $0; the cap uses the paid price so it stays meaningful.

### 22. Can the free Gemini tier run the eval?
- **Answer:** No. The free tier allows **20 requests per day** per model (`quotaValue: 20`, from a 429 on 2026-11-01), on top of 5 per minute. One eval run needs ~100. A bug made it worse: the client honoured the server's suggested wait (74,088 s), so every question hung until the 90 s step timeout. Now any suggested wait over 60 s fails fast as "quota exhausted".
- **Outcome:** decision. The retrieval experiment needs no model (BM25 vs vector vs hybrid on recall@5/MRR). The agent eval moves to a second provider through a new OpenAI-compatible adapter (GitHub Models, Groq, OpenRouter, Ollama by config). That also proves the model port with a second real provider.

### 23. Why are m3 and m5 not scored in the retrieval experiment?
- **Answer:** Their question text does not contain the search terms ("Issue #3 mentions an error code…"); the agent finds them only after `get_issue`. Searching the raw question scores 0 in every mode, which measures the question, not the retriever. They are listed as not scored and still count in the agent eval.
- **Outcome:** decision.
