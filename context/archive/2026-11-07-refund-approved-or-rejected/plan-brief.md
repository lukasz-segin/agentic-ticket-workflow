# Refund Approved or Rejected — Plan Brief

> Full plan: `context/changes/refund-approved-or-rejected/plan.md`

## What & Why

A support agent must be able to approve or reject T-2's proposed refund (INV-1002, 49.0 EUR). An approved refund is issued exactly once, even when the helpdesk fails at random. A rejected one closes the ticket with no refund. This is roadmap S-05 (US-02, FR-006, FR-011 b), the highest-money-risk slice: no refund is ever issued without a person.

## Starting Point

A refund that passes the S-04 rules is currently replaced by a placeholder `escalate(refund_needs_approval)` (`workflow.py:122-125`). The helpdesk already dedupes on `{workflow_id}:{action.type}`, so `ticket-T-2:refund` can be performed at most once. There is no approval endpoint yet.

## Desired End State

T-2 waits at a new `awaiting_approval` step with the refund visible in `GET /tickets/T-2`. `POST /tickets/T-2/approval {"approved": true|false, "approver"?, "comment"?}` answers 200 as soon as the approval is recorded. The workflow then issues the refund once, or closes the ticket with `refund_rejected[: comment]`. Approvals for a ticket that isn't waiting get 409, and approvals for an unknown ticket get 404. The approver name and comment are kept on the ticket.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Approval mechanism | Temporal Update + validator, sync handler with a defensive re-check | The validator refuses with 409 before anything is written to history (shape-notes design note). The SDK runs validator and sync handler back to back; the re-check keeps "first wins" if the handler ever becomes async. |
| 24 h timeout | Deferred to S-06 | Keeps the roadmap slice boundaries; S-06 adds `timeout=24h` to this same wait. |
| Audit log | Log `approved` + `approver` (capped); comment only in status | Records who decided what, while free-form comments that may quote the ticket stay out of the logs (FR-010). |
| Reject reason | `refund_rejected: <comment>`, else `refund_rejected` | Always starts with a code you can filter on, and still quotes the comment as the PRD asks. |
| Endpoint response | 200 once recorded; refund happens asynchronously | Never blocks on helpdesk retries; matches `POST /tickets`. |
| Exactly-once proof | Real `act` with a scripted helpdesk that records the refund and then loses the response | Exercises the dedupe path through a real Temporal retry, not just a retry before recording. |
| Body shape | One `Approval` model (`approved`, `approver`, `comment`) for request, Update arg and status | One type to validate and to store. |

## Scope

**In scope:** the approval wait, the Update and validator, approve → refund and reject → close, the status `approval` field and new step, audit log fields, `POST /tickets/{id}/approval` with 200/404/409/422/503, workflow and API tests, README notes.

**Out of scope:** the 24 h timeout (S-06), logging the comment, changing the amount at approval, idempotent repeat approvals (FR-006 says 409), signal-based approvals, auth.

## Architecture / Approach

```
POST /tickets/{id}/approval ─► describe() ─ missing ► 404 · not running ► 409
                              └► execute_update(approve) ─ validator/handler refuse ► 409
                                                          └► recorded ► 200
TicketWorkflow: checking ─► awaiting_approval ── wait_condition(approval) ──► acting ─► done
                                                   approved: RefundAction (key …:refund)
                                                   rejected: CloseAction  (key …:close)
```

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Workflow approval wait | Models, Update + validator, approve/reject paths, log fields, workflow tests (incl. concurrent approve/reject) | Racing approvals: keep the handler sync and the re-check in place |
| 2. Approval endpoint & README | HTTP endpoint with FR-006 codes, API tests (real server plus a stub for Update-stage errors), README notes | Mapping "closed between describe and update" to 409, not 500 |

**Prerequisites:** S-04 done (it is).
**Estimated effort:** ~1 session, 2 phases.

## Open Risks & Assumptions

- The time-skipping test server supports Updates (expected in temporalio 1.35). If not, the workflow tests need the dev server instead.
- The exact RPC status for "an Update to a workflow that closed after `describe()`" isn't observed against a real server. The API maps both likely codes (`NOT_FOUND`, `FAILED_PRECONDITION`) to 409, and stub-client tests pin that mapping. The finished-T-1 test covers only the `describe()` branch.
- Workflows started on the old code and still open break replay on the new worker. Locally, let them finish, or use `docker compose down -v` or a separate Compose project (`down` alone keeps the volume).
- Logging the approver name departs from the lesson's "code-produced values only" posture, by explicit user decision (an audit trail).

## Success Criteria (Summary)

- T-2 waits for a person, and an approval issues exactly one 49.0 EUR refund, even at a 30% helpdesk failure rate.
- A rejection closes the ticket with no refund and the comment as the reason.
- Late, repeated or misdirected approvals get 409 or 404 and never issue a refund.
