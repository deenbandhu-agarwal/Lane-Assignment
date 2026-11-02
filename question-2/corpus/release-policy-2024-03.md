---
title: Release policy
date: 2024-03-12
owner: Payments Core
---
# Release policy

## Merging to main
Every pull request needs **1 approval** from any engineer on the owning team before it can be merged to `main`. Self-approval is not allowed. The author merges once the approval is in and checks are green.

## Release schedule
We ship a release train every **Tuesday** at 14:00 UTC. Anything merged to `main` by Monday 18:00 UTC goes out on the next train.

## Hotfixes
Hotfixes may be released on any day. They still need the normal approval, and the on-call engineer for the owning team must be told in #ledgerly-oncall before the deploy starts.

## Release notes
The release captain writes release notes in the `CHANGELOG.md` file, grouped by service.
