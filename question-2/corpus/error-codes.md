---
title: API error codes
date: 2025-11-14
owner: Platform
---
# API error codes

Ledgerly API errors return a JSON body with `code`, `message` and `request_id`.

## E4012: access token expired
The bearer token is past its expiry. Clients must call `POST /auth/refresh` with their refresh token and retry the original request once. If the refresh also fails, the user must sign in again. Do not retry in a loop.

## E4090: duplicate idempotency key
The `Idempotency-Key` header was already used with a different request body in the last 24 hours. Generate a new key for a new operation; reuse the same key only for exact retries.

## E4221: currency mismatch
The payment currency does not match the currency of the merchant ledger account. Convert on the client or open a ledger account in that currency.

## E5031: ledger write timeout
The ledger did not confirm the write within 2 seconds. The write may still succeed. Retry with the same idempotency key, using exponential backoff starting at 200 ms, at most 5 attempts.
