---
title: Service ownership
date: 2026-02-03
owner: Engineering management
---
# Service ownership

This page lists which team owns each Ledgerly service. The owning team reviews changes, handles incidents and decides on deprecations.

| Service | Owning team | Repo path |
|---|---|---|
| payments-api | Payments Core | `services/payments-api` |
| ledger-service | Payments Core | `services/ledger` |
| auth-service | Platform | `services/auth` |
| api-gateway | Platform | `services/gateway` |
| checkout-web | Growth | `apps/checkout` |
| notifications | Growth | `services/notifications` |

## Shared code
`libs/money` (currency and rounding helpers) is jointly owned by Payments Core and Platform. Changes need one approver from each team.

## Changing ownership
Ownership changes are proposed in the #eng-leads channel and recorded here by an engineering manager.
