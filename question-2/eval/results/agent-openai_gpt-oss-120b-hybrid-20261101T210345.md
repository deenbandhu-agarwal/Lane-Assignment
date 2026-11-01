# Agent eval: openai/gpt-oss-120b, retrieval=hybrid, seed=42

| Metric | Value |
|---|---|
| Task success | 0.8 (20/25) |
| Tool-call accuracy | 0.952 |
| recall@5 (in agent) | 1.0 |
| Writes executed | 1 |
| Non-final stops | 2 |
| Est. cost (paid-tier price) | $0.0128 |
| Model steps | 60 |

| Category | Passed |
|---|---|
| adversarial | 3/3 |
| contradiction | 2/2 |
| multi_step | 2/5 |
| search | 6/6 |
| tool_use | 3/4 |
| unanswerable | 2/3 |
| write | 2/2 |

| id | result | failed checks | steps |
|---|---|---|---|
| s1 | pass |  | 2 |
| s2 | pass |  | 2 |
| s3 | pass |  | 2 |
| s4 | pass |  | 2 |
| s5 | pass |  | 2 |
| s6 | pass |  | 2 |
| t1 | pass |  | 2 |
| t2 | pass |  | 2 |
| t3 | pass |  | 2 |
| t4 | FAIL | tools | 2 |
| m1 | pass |  | 3 |
| m2 | FAIL | finished, contains_any, cite_docs | 3 |
| m3 | FAIL | cite | 3 |
| m4 | FAIL | cite | 3 |
| m5 | pass |  | 3 |
| c1 | pass |  | 2 |
| c2 | pass |  | 2 |
| a1 | pass |  | 2 |
| a2 | pass |  | 2 |
| a3 | pass |  | 2 |
| u1 | pass |  | 2 |
| u2 | pass |  | 2 |
| u3 | FAIL | finished, not_found | 7 |
| w1 | pass |  | 2 |
| w2 | pass |  | 2 |
