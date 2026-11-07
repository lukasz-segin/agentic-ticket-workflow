# Refund Timeout Escalated — Plan Brief

> Full plan: `context/changes/refund-timeout-escalated/plan.md`

## What & Why

A valid refund waits for a person to approve or reject it. Today that wait has no end. This slice (S-06: US-04, FR-006, FR-011 c) adds a 24 h limit. With no answer in time, the ticket escalates with reason `approval_timeout`, nothing is refunded, and any later approval is refused as a conflict. A late approval can never issue a refund.

## Starting Point

S-05 built the wait: `workflow.wait_condition(lambda: approval is not None)` in the workflow's refund branch, with no timeout. The `approve` Update validator already refuses an approval unless the ticket is at `awaiting_approval` with no answer yet. The API already maps a closed workflow to 409.

## Desired End State

An unanswered T-2 is escalated 24 h after it started waiting, and the helpdesk never sees a refund. An approval after that gets 409, while the ticket is still acting and also after it has finished. An approval at 23 h 59 m still refunds exactly once. `GET /tickets/{id}` shows `approval_deadline` while the ticket waits.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Reason code | `approval_timeout` | Short snake_case code like `unknown_customer` / `refund_rejected`; safe to log as `reason_code`. |
| `violation` field | Not used for the timeout | A timeout is not a broken decision rule (FR-005). |
| Deadline definition | Fixed `timedelta(hours=24)` constant | A fixed business rule; no config for fixed values; tests use time skipping. |
| Deadline visibility | New `TicketStatus.approval_deadline` from `workflow.now()` | The agent can see how long is left; deterministic and survives restarts. |
| Deadline enforcement | The validator also refuses when `workflow.now() >= approval_deadline` | Updates run before timers in an activation, so a step-only check could refund an approval queued during worker downtime (review F1). |
| After-wait branch | Decide from the recorded approval, not from the timeout firing | A defensive check: never tell a caller 200 and then escalate anyway. |
| Versioning | No `workflow.patched()` | Nothing is deployed; the README documents `docker compose down -v` (it deletes local histories). |
| Tests | FR-011(c) + late approval (workflow) + 23 h 59 m boundary + approval queued during downtime + late approval via HTTP | Proves the escalation, the refusal, the boundary, the downtime race and the external contract. Time skips happen only while the workflow waits, and only up to the recorded deadline (review F2). |

## Scope

**In scope:** a timeout on the existing wait, the escalation on expiry, the `approval_deadline` status field, a timeout log line, 3 workflow tests and 1 API test, and README updates.

**Out of scope:** a configurable timeout, workflow versioning, a new step value, API code changes, reminders, extending the deadline.

## Architecture / Approach

The plan changes one branch in `TicketWorkflow.run`:
1. Set `approval_deadline = now + 24h`.
2. Enter `awaiting_approval`.
3. Run `wait_condition(..., timeout=24h, timeout_summary="approval_timeout")`.
4. Catch `asyncio.TimeoutError`, then branch on whether an approval was recorded: none → escalate, rejected → close, approved → refund.

The shared validator/handler guard also refuses once `workflow.now() >= approval_deadline`, so even an approval delivered together with the overdue timer (Updates run first) is refused. No API change is needed.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Timeout in the workflow and status | Bounded wait, deadline check in the validator, escalation, `approval_deadline`, 4 time-skipped workflow tests | Reproducing the downtime race in the test server (two workers on one task queue) |
| 2. HTTP late-approval test and README | End-to-end 409 proof and documentation | Little; the time-skip mechanics in the API test |

**Prerequisites:** S-05 done (it is).
**Estimated effort:** about 1 short session.

## Open Risks & Assumptions

- Adding the timer is nondeterministic for refunds already waiting in a running dev server. They need a reset with `docker compose down -v`, which deletes all local histories; the README documents it.
- The F1 race (an overdue timer and a queued Update in one activation) was found by reading the source, not by running it. The regression test must show it fails without the validator's deadline check.
- Assumption: the 24 h clock starts when the ticket enters `awaiting_approval`, not when it was submitted.

## Success Criteria (Summary)

- T-2 with no answer escalates with `approval_timeout` after 24 h, and nothing is refunded.
- A late approval returns 409 and never refunds. An on-time approval still refunds exactly once.
- `uv run pytest` and ruff pass.
