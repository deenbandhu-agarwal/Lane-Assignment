---
title: API rate limits
date: 2026-01-20
owner: Platform
---
# API rate limits

Limits are applied per API key by api-gateway.

| Plan | Requests per second | Burst |
|---|---|---|
| Starter | 25 | 50 |
| Growth | 100 | 200 |
| Enterprise | 500 | 1000 |

When a client goes over the limit, the gateway returns HTTP 429 with a `Retry-After` header in seconds. Clients should wait at least that long before retrying.

Webhook endpoints and `/auth/refresh` are not rate limited per key; they have a global limit of 2,000 requests per second.

Temporary limit increases for launches can be requested from Platform at least 5 business days in advance.
