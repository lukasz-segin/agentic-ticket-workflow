---
change_id: example-tickets-triaged
title: Example tickets triaged
status: impl_reviewed
created: 2026-11-07
updated: 2026-11-07
archived_at: null
---

## Notes

- **Watch item (Phase 2 manual run, 2026-11-07):** on the first T-7 run after `docker compose up --build`, the workflow task that handled the `unknown_customer` decide failure timed out once after 10 s (`WORKFLOW_TASK_TIMED_OUT`, no worker log), then completed on retry with the right result and a single `decide` attempt. It didn't happen again in five more tries (running worker, after a restart, and on a fresh worker). The likely cause is the worker being swapped during the rebuild; that's unverified. Watch for it in S-07, which adds more error-to-escalation paths.
