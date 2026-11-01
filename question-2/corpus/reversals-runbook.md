---
title: Returning funds to a cardholder
date: 2025-08-05
owner: Payments Core
---
# Returning funds to a cardholder

Use this runbook when a customer should get their money back, for example after a duplicate charge or a cancelled order.

## Full reversal
1. Find the original charge in the admin console by its charge id.
2. Choose **Reverse charge**. The full amount goes back to the original card.
3. The ledger records a reversal entry linked to the original charge.

## Partial reversal
Enter the amount to return. Partial reversals are allowed up to 90 days after the charge and up to the captured amount minus earlier reversals.

## Timing
Funds normally reach the cardholder in 5 to 10 business days, depending on the card issuer. We cannot speed this up.

## Approvals
Reversals above 5,000 USD need a second person from Payments Core to confirm in the console before they are sent.
