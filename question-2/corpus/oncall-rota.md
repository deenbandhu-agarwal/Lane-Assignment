---
title: On-call rota, November 2026
date: 2026-10-28
owner: Engineering management
---
# On-call rota, November 2026

Primary on-call per team for November 2026. Shifts run Monday 09:00 UTC to the following Monday 09:00 UTC; the person below is primary for the whole month and arranges swaps themselves.

| Team | Primary on-call | Secondary |
|---|---|---|
| Payments Core | Priya Raman | Tomasz Nowak |
| Platform | Marcus Webb | Lena Fischer |
| Growth | Aiko Tanaka | Daniel Okafor |

## Paging
Page the primary through PagerDuty service `ledgerly-<team>`. If there is no acknowledgement within 10 minutes, PagerDuty escalates to the secondary, then to the engineering manager.

## Handover
Outgoing on-call posts a short handover in #ledgerly-oncall listing open incidents and anything flaky.
