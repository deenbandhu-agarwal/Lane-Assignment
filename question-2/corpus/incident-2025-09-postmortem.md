---
title: Postmortem, ledger write timeouts on 2025-09-18
date: 2025-09-22
owner: Payments Core
---
# Postmortem: ledger write timeouts, 2025-09-18

## Summary
For 47 minutes, about 12% of payment captures failed with E5031 (ledger write timeout). No money was lost; affected clients retried successfully after the fix.

## Cause
A new index on the ledger entries table was created without `CONCURRENTLY`, which locked writes on the largest partition.

## Detection
The ledger write latency alert fired 6 minutes after the migration started. On-call paged the database owner.

## Fix
The migration was cancelled and the index was rebuilt concurrently the same night.

## Follow-ups
- Migrations that create indexes must use `CONCURRENTLY` (added to the review checklist).
- Add a staging load test that runs migrations under write traffic.
