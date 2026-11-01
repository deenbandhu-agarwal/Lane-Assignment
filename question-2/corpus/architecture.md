---
title: Architecture overview
date: 2025-12-01
owner: Platform
---
# Architecture overview

## Request path
Client requests enter through **api-gateway**, which terminates TLS, checks the access token with **auth-service**, applies rate limits and routes to the backing service.

## Payments flow
**payments-api** validates a payment, calls the card acquirer and, once the acquirer accepts, asks **ledger-service** to write double-entry records. The ledger is the source of truth for balances.

## Data stores
payments-api and ledger-service each use their own PostgreSQL database. The ledger database is append-only: corrections are new entries, never updates. Redis is used by api-gateway for rate-limit counters.

## Async work
Events (payment captured, reversal created) are published to Kafka. **notifications** consumes them to send emails and webhooks to merchants.

## Environments
We run `staging` and `production` in separate AWS accounts. Staging data is synthetic.
