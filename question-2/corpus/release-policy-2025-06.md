---
title: Release and merge rules
date: 2025-06-20
owner: Platform
---
# Release and merge rules

## Approvals
A pull request needs **2 approvals** before merge, and at least one of them must come from a code owner of the files touched (see `CODEOWNERS`). Approvals are dismissed automatically when new commits are pushed.

## Release day
Releases go out on **Wednesdays** at 15:00 UTC. The cut-off for the Wednesday release is Tuesday 20:00 UTC.

## Freeze windows
There are no releases during the last two business days of a calendar month, because finance reconciliation runs then. Hotfixes during a freeze need sign-off from the Payments Core lead.

## Rollback
Every release must have a rollback plan written in the release ticket. Rollbacks use the previous container image tag; database migrations must be backwards compatible for one release.
