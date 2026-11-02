---
title: How to deploy a service
date: 2025-07-15
owner: Platform
---
# How to deploy a service

## Before you deploy
Make sure the change is merged and the container image for the merge commit has been built and pushed. Check the release calendar for freeze windows.

## Steps
1. Open the deploy tool and pick the service and the image tag.
2. Deploy to `staging` first and watch the service dashboard for 15 minutes.
3. Promote the same tag to `production`. The tool rolls out 10% of pods, waits 10 minutes, then the rest.
4. Post the deployed tag in #ledgerly-deploys.

## If something goes wrong
Press **Roll back** in the deploy tool; it redeploys the previous tag. Tell the owning team's on-call engineer.
