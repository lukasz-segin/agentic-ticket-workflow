<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Refund Timeout Escalated

- **Plan**: context/changes/refund-timeout-escalated/plan.md
- **Scope**: Full plan, Phases 1–2 of 2; 8/8 Progress items complete
- **Date**: 2026-11-08
- **Revision**: 1070e0d8c09a70bd65664849a29128c4a6484852
- **Compared with**: 7c17609 (before the two implementation commits)
- **Verdict**: APPROVED
- **Findings**: 0 critical, 1 warning, 0 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | WARNING |

No production-code defect was identified. The remaining warning concerns evidence for the planned regression-test negative control. Approval includes this minor verification warning.

## Findings

### F1 — Record the downtime regression test's negative-control result

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: tests/test_workflow.py:301
- **Detail**: The plan at line 99 explicitly asks to remove the validator's deadline check temporarily, confirm the downtime test fails, and note whether the same-activation ordering was observed. The test explains the intended ordering but does not record a negative-control result, and neither the change artifacts nor implementation commit messages supply one. Its fixed 0.5-second delay and `not late.done()` assertion do not themselves prove the Update has reached the server before the replacement worker starts. If the timer is processed first, a step-only guard can also refuse the approval, so a passing test alone does not establish that the deadline check is protected. The normal test passes; this review does not claim the test is ineffective. An attempted process-local import mutation was blocked before Python started by uv cache lock permissions, so sensitivity could not be independently confirmed here.
- **Fix**: Run the existing test against an isolated variant with only the deadline clause removed, confirm it fails because the overdue approval is accepted, then record that outcome beside the test or in a change-scoped verification note. If it still passes, synchronize the Update's arrival before restarting the worker and repeat.
- **Decision**: FIXED — negative control run on 2026-11-08: with only the deadline clause removed from `_refuse_unless_awaiting_approval`, the test failed 3/3 (`DID NOT RAISE WorkflowUpdateFailedError`, overdue approval accepted), which confirms the same-activation order (Update before timer). Source restored via `git checkout`, and the guarded test passes again. Result recorded in the test's comment at tests/test_workflow.py:304.

## Plan comparison

| Planned item | Actual implementation | Verdict |
|--------------|-----------------------|---------|
| Nullable UTC approval deadline in status | `TicketStatus.approval_deadline: datetime \| None = None`; workflow sets it from its deterministic clock | MATCH |
| Fixed 24-hour durable wait and named timer | `APPROVAL_TIMEOUT = timedelta(hours=24)` and `timeout_summary="approval_timeout"` | MATCH |
| Escalate unanswered refund through existing action activity | Timeout selects `EscalateAction`; proposed decision stays visible; approval and violation remain unset | MATCH |
| Reject at and after the deadline, including downtime | Shared validator/handler guard compares `workflow.now() >= approval_deadline` | MATCH |
| Honour an approval accepted before expiry | Post-wait branch uses recorded approval; existing approval/rejection paths retained | MATCH |
| Four workflow scenarios | Timeout, refusal while acting, 23h59m approval, and worker-downtime test present and passing | MATCH; negative-control evidence tracked in F1 |
| HTTP timeout and late-approval contract | API test verifies 202, visible deadline, completed escalation, 409, unchanged deadline and no refund key | MATCH |
| README behavior and migration limitation | Deadline, durable timer, late approvals, fixed duration, and destructive local reset warning documented | MATCH |

Two implementation adjustments preserve intent: `suppress(TimeoutError)` handles the wait exception instead of an explicit `except asyncio.TimeoutError`; the downtime test advances time before queuing the Update because its comment explains the test server cannot skip while an Update is pending. The API test explicitly advances to the deadline instead of relying on automatic skipping from a retrieved handle. None requires a product or architectural change.

The diff contains the five planned product/test files (`models.py`, `workflow.py`, `test_workflow.py`, `test_api.py`, README), plus the change's planning/review artifacts and roadmap bookkeeping. These supporting changes are appropriate. API endpoint code, business rules, settings, retry policies and Step values are unchanged. Configurable timeouts, reminders and workflow versioning remain outside scope as planned.

## Safety, architecture and patterns

- Deadline assignment and entry into `awaiting_approval` have no intervening await. Queries and validators therefore observe the deadline with the waiting step.
- Both validator and synchronous Update handler use the same refusal guard. Equality counts as expired; the action is selected from recorded approval after waiting.
- Expiry uses the existing escalation action and idempotency key (`ticket-T-2:escalate`), with the existing bounded Helpdesk retries. No unchecked refund reaches the activity.
- The new log contains only a fixed message, action type and reason code; it uses the existing replay-aware logger and preserves the accepted lesson about ticket-derived text.
- The nullable status field is inherited by the HTTP view. The existing HTTP error mapping handles late approvals; no new API surface or framework dependency was introduced into business rules.
- New tests follow the existing worker, fake-activity, query-polling and refusal helpers. The gated activity is released without skipping beyond its timeout.
- The deliberately unversioned workflow change and the local-history reset cost are documented, consistent with the plan's undeployed/local-only scope.

## Automated verification

Commands were run against the reviewed checkout. Repeated criteria shared by both phases were verified once with the full suite, in addition to both targeted suites.

| Command | Result | Observed output |
|---------|--------|-----------------|
| `uv run pytest tests/test_workflow.py` | PASS | 29 passed in 18.40s |
| `uv run pytest tests/test_api.py` | PASS | 10 passed in 7.37s |
| `uv run pytest` | PASS | 104 passed in 26.55s |
| `uv run ruff check` | PASS | All checks passed! |
| `uv run ruff format --check` | PASS | 68 files already formatted |

Supplemental negative-control attempt: a process-local import hook was intended to omit only the deadline guard and execute the existing downtime test, without modifying source files. `uv run python -` exited before executing Python: `Could not acquire lock`, access denied for `C:\Users\lukas\AppData\Local\uv\cache\.lock`. No conclusion about mutation sensitivity follows from that infrastructure failure. No broader permissions were requested in this side conversation.

## Manual criteria and evidence

- **1.4 — marked complete.** An existing screenshot at `C:\Users\lukas\AppData\Local\Temp\atw-s06-temporal-ui.png` was inspected. It shows running `ticket-T-2`, run `01a1b82c-82fc-7618-a1b1-c9bccb84e5ee`, and Timer Started event 17 with Start To Fire Timeout `1 day` and Summary `approval_timeout`. This supports the timer/UI portion. The README's waiting-status example includes the corresponding UTC deadline; the passing API test independently verifies deadline exposure and retention. A fresh GET to `localhost:8000/tickets/T-2` could not connect, so a current Compose HTTP response was not independently observed. The screenshot is a temporary local artifact, not committed review evidence.
- **2.4 — marked complete and checked.** README now describes expiry and the deadline boundary; the obsolete statement deferring the timeout to S-06 is removed.

## Review method and limits

Both completed phases were reviewed directly against the plan, PRD, required stack, infrastructure, scaffold verification, accepted lessons and surrounding code. No sub-agents were used because this side conversation prohibits them. No service was started, ticket submitted, workflow history reset or production source edited. This review writes only its report and the required `change.md` status/date stamp.
