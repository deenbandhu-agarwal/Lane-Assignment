# Retrieval experiment (bge-small-en-v1.5, 59 chunks, k=5)

11 answerable questions with labelled chunks, 3 unanswerable. Not scored (search terms come from a GitHub tool call first): m3, m5.

| Mode | recall@5 | MRR | full recall (all chunks in top 5) | abstained on unanswerable |
|---|---|---|---|---|
| bm25 | 0.909 | 0.932 | 9/11 | 1/3 |
| vector | 1.000 | 0.758 | 11/11 | 1/3 |
| hybrid | 1.000 | 0.841 | 11/11 | 1/3 |

| id | expected | bm25 | vector | hybrid |
|---|---|---|---|---|
| s1 | error-codes.md#2 | 1.00 | 1.00 | 1.00 |
| s2 | reversals-runbook.md#1, reversals-runbook.md#2 | 0.50 | 1.00 | 1.00 |
| s3 | data-retention.md#2 | 1.00 | 1.00 | 1.00 |
| s4 | api-rate-limits.md#1 | 1.00 | 1.00 | 1.00 |
| s5 | error-codes.md#5 | 1.00 | 1.00 | 1.00 |
| s6 | incident-2025-09-postmortem.md#2 | 1.00 | 1.00 | 1.00 |
| m1 | team-owners.md#1, oncall-rota.md#1 | 1.00 | 1.00 | 1.00 |
| m2 | team-owners.md#1, oncall-rota.md#1 | 1.00 | 1.00 | 1.00 |
| c1 | release-policy-2025-06.md#1, release-policy-2024-03.md#1 | 1.00 | 1.00 | 1.00 |
| c2 | release-policy-2025-06.md#2, release-policy-2024-03.md#2 | 1.00 | 1.00 | 1.00 |
| a1 | vendor-integration-notes.md#2, vendor-integration-notes.md#5 | 0.50 | 1.00 | 1.00 |
