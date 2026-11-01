---
title: Coding standards
date: 2025-03-10
owner: Engineering management
---
# Coding standards

## Money
Never use floating point for money. Use integer minor units (cents) plus an ISO 4217 currency code, through the helpers in `libs/money`. Rounding is banker's rounding.

## Errors
Return the documented API error codes. Never leak stack traces or internal hostnames in API responses.

## Logging
Log in JSON. Every log line carries `request_id`. Card numbers, CVV and full names must never be logged; use the masking helpers.

## Tests
Every bug fix comes with a test that fails before the fix. Services keep line coverage above 80%.

## Pull requests
Keep pull requests under 400 changed lines where possible and link the issue they fix with `Fixes #<number>`.
