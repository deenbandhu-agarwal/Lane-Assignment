# Experiment: BM25 vs vector vs hybrid retrieval

## Question

Does hybrid retrieval (BM25 + vectors, fused with RRF) find the right notes better than
either method alone on this corpus?

## Setup: one variable

Only the retrieval mode changes. Everything else is fixed:

| Fixed | Value |
|---|---|
| Corpus | 15 Ledgerly notes → 59 chunks (heading-aware, max 220 words) |
| Embedder | `BAAI/bge-small-en-v1.5` (local, fastembed) |
| Query | the golden question text, unchanged |
| k | 5 (what the agent sees per search) |
| Relevance floors | BM25 ≥ 3.0, cosine ≥ 0.60 (below both → "no results") |
| Questions | 11 answerable questions with labelled chunks + 3 unanswerable |

No LLM is involved, so the run is deterministic and free:
`uv run python eval/experiment.py` (offline smoke version: `--fake-embedder`).
Raw output: `eval/results/retrieval-experiment-bge-small-en-v1.5.{md,jsonl}`.

**Excluded: m3 and m5.** Their search terms only exist after a GitHub call ("Issue #3
mentions an error code…": the code E4012 is in the issue, not the question). Searching the
question text would test the wrong thing. They are covered by the agent eval instead.

## Metrics

- **recall@5**: share of the labelled chunks that appear in the top 5.
- **MRR**: 1 / rank of the first labelled chunk (1.0 = it was first).
- **Full recall**: questions where *all* labelled chunks were in the top 5.
- **Abstained**: unanswerable questions where search returned nothing.

## Results

| Mode | recall@5 | MRR | Full recall | Abstained on unanswerable |
|---|---|---|---|---|
| BM25 | 0.909 | **0.932** | 9/11 | 1/3 |
| Vector | **1.000** | 0.758 | **11/11** | 1/3 |
| Hybrid | **1.000** | 0.841 | **11/11** | 1/3 |

Where the modes differ (all other questions: all three modes found everything at rank 1):

| Question | BM25 | Vector | Hybrid | Why |
|---|---|---|---|---|
| s2 "How do I **refund** a customer charged twice?" | misses `reversals-runbook#2` | finds both | finds both | The runbook says "reversal", never "refund". Keywords can't bridge a synonym; embeddings can. |
| a1 "Summarize the PayFlex vendor notes" | misses `vendor-integration-notes#2` | finds both | finds both | The wanted chunk shares few words with the question. |
| s1 "What does error code **E4012** mean?" | rank 1 | rank 4 | rank 2 | An exact code is a keyword match. Vectors see "an error-code chunk" and rank the overview first. |
| m1 "primary on-call for the team that owns ledger-service" | rank 1 | rank 4 (onboarding first) | rank 2 | Names and service ids are exact terms; vectors drift to the generic onboarding page. |

## What this shows

1. **Hybrid gets vector's recall and recovers part of BM25's ranking.** It found every labelled
   chunk (like vector) and moved exact-term answers (E4012, team names) back up from rank 4 to 2.
2. **BM25 alone ranks best but misses synonyms.** It has the highest MRR, but 2 of 11 questions
   lose a needed chunk entirely, and a chunk that is not retrieved cannot be cited.
3. **Recall@5 is the metric that matters here, not MRR.** The agent puts all 5 results in the
   model's context, so rank 1 vs rank 2 changes little. Missing a chunk changes the answer. That
   is why hybrid is the default (`RETRIEVAL_MODE=hybrid`) even though BM25 has the better MRR.
4. **Retrieval alone does not abstain well (1/3 for every mode).** For "office address" and
   "salary bands", weak chunks pass the floors (on-call rota, onboarding). Only "2023 roadmap"
   returns nothing. Saying "not found" therefore depends on the model reading the results
   critically. In the agent eval the model did that for u1 and u2 in every run. u3 then failed
   in runs 2–4 for model and provider reasons, not retrieval: it returned nothing every time.

## Limits

- **Small.** 11 questions, so one question moves recall@5 by 0.09. The direction (synonyms need
  vectors, exact codes need keywords) matches the per-question evidence, but no claim is made
  about the size of the gap on a larger corpus.
- **Labels are mine.** I wrote the corpus and labelled the chunks, so the questions may be easier
  than real usage. The traps (synonym, stale vs new policy, injection) were planted on purpose.
- **Floors were set on this same corpus**, so the abstention numbers are optimistic if anything.
- **Fake-embedder run** (`retrieval-experiment-fake.md`): vector and hybrid drop to 0.909 / 9/11
  because hashed bag-of-words cannot bridge "refund" → "reversal". It proves the experiment runs
  offline; it says nothing about real semantic quality.

## What I'd do next

- A cross-encoder reranker on the top 20 to fix the rank-4 cases without losing recall.
- Calibrate the floors on held-out questions, or replace them with a reranker score threshold,
  to improve abstention.
- A larger, independently labelled question set before trusting any gap smaller than ~0.1.
