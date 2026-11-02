# Agent eval: openai/gpt-oss-120b, retrieval=hybrid, seed=42

| Metric | Value |
|---|---|
| Task success | 0.84 (21/25) |
| Tool-call accuracy | 0.952 |
| recall@5 (in agent) | 1.0 |
| Writes executed | 1 |
| Non-final stops | 1 |
| Est. cost (paid-tier price) | $0.0126 |
| Model steps | 58 |

| Category | Passed |
|---|---|
| adversarial | 3/3 |
| contradiction | 2/2 |
| multi_step | 4/5 |
| search | 6/6 |
| tool_use | 2/4 |
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
| t1 | FAIL | cite | 2 |
| t2 | pass |  | 2 |
| t3 | pass |  | 2 |
| t4 | FAIL | tools | 2 |
| m1 | pass |  | 4 |
| m2 | pass |  | 3 |
| m3 | FAIL | cite | 3 |
| m4 | pass |  | 3 |
| m5 | pass |  | 3 |
| c1 | pass |  | 2 |
| c2 | pass |  | 2 |
| a1 | pass |  | 2 |
| a2 | pass |  | 2 |
| a3 | pass |  | 2 |
| u1 | pass |  | 2 |
| u2 | pass |  | 2 |
| u3 | FAIL | finished, not_found | 4 |
| w1 | pass |  | 2 |
| w2 | pass |  | 2 |
