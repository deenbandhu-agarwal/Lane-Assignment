---
title: Glossary
date: 2025-10-02
owner: Payments Core
---
# Glossary

**Acquirer**: the bank or processor that accepts card payments on behalf of a merchant. PayFlex is our EU acquirer.

**Capture**: the step that actually moves the money after an authorization.

**Authorization**: a hold on the cardholder's funds, not yet moved.

**Idempotency key**: a client-chosen value that makes retries safe; the same key with the same body returns the original result.

**Ledger entry**: one immutable double-entry record in ledger-service.

**Minor units**: the smallest unit of a currency, such as cents.

**Reversal**: returning funds from a captured charge to the cardholder.

**Settlement**: the acquirer paying out captured funds to the merchant's bank account.
