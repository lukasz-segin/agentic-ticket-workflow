# Refund Timeout Escalated Implementation Plan

## Overview

This change gives the refund approval wait a fixed 24 h deadline. If no one approves or rejects a valid refund in time, the ticket escalates with reason `approval_timeout` and nothing is refunded. An approval sent after that is refused as a conflict (409). While the ticket waits, its status shows when the wait ends. This is roadmap slice S-06 (US-04, FR-006, FR-011 c).

## Current State Analysis

- `src/agentic_ticket_workflow/workflow.py`, in `run`'s `elif action.type == "refund":` branch: the ticket enters `awaiting_approval`, then `await workflow.wait_condition(lambda: self._status.approval is not None)` waits **with no timeout**. The comment there says "S-06 adds the 24 h timeout here".
- The refusal path already exists. `_refuse_unless_awaiting_approval` (used by both the `approve` validator and the handler) refuses unless `step == "awaiting_approval"` and no approval is recorded. Once the workflow has moved to `acting` or finished, every approval is refused. A closed workflow is refused at the API's `describe()` stage (`api.py` `approve_ticket`, `status != RUNNING` → 409).
- `TicketStatus` (`models.py`) has no deadline field. `Step` needs no new value: a timed-out refund goes `awaiting_approval → acting → done`, like the reject path.
- Escalation reasons are code-produced snake_case strings (`unknown_customer`, rule codes, `refund_rejected`), logged under `reason_code`, which the formatter allow-lists.
- Tests: `tests/conftest.py` `env` is `WorkflowEnvironment.start_time_skipping` with the pydantic converter. `tests/test_workflow.py` has `fake_activities(..., act_gate=)`, `started`, `wait_for_step`, `assert_refused`, `T2_DECISION` and `T2_REFUND`. `tests/test_api.py` has `api_and_worker` and its own HTTP `wait_for_step`.
- README: line 85 says "For now the wait has no time limit; the 24 h timeout comes with S-06". Line 53 lists the 409 cases.

## Desired End State

- A valid refund with no answer for 24 h after it entered `awaiting_approval` ends with `result.action == EscalateAction(reason="approval_timeout")`. The steps are `[received, deciding, checking, awaiting_approval, acting, done]`, `approval` is `None`, and the helpdesk never sees `ticket-<id>:refund`.
- An approval after the deadline returns 409 (`not_awaiting_approval`) while the ticket is still acting, and also after it has finished. That includes an approval queued while the worker was down and delivered together with the overdue timer. No refund is issued.
- An approval just before the deadline (23 h 59 m) still issues the refund exactly once.
- `GET /tickets/{id}` shows `approval_deadline` (UTC datetime) from the moment the ticket waits. It stays set after the ticket finishes, and it is `null` for tickets that never waited.
- The deadline is a durable Temporal timer, so a worker restart keeps it unchanged (NFR, prd.md:161).
- `uv run pytest`, `uv run ruff check` and `uv run ruff format --check` pass.

### Key Discoveries:

- `workflow.wait_condition(fn, *, timeout=None, timeout_summary=None, ...)` raises `asyncio.TimeoutError` on timeout (temporalio 1.35.0 docstring). Changing `timeout` from `None` to a value creates a timer. That is a **nondeterministic change** for workflows already waiting under the old code.
- `workflow.now()` is the deterministic workflow clock to use for `approval_deadline`.
- `rules.py` / `ESCALATE_ON_ERROR` are untouched. The timeout isn't a decision-rule breach, so `violation` stays `None`.

## What We're NOT Doing

- No configurable timeout (env var or workflow input). 24 h is a fixed business rule, and tests use time skipping.
- No `workflow.patched()` versioning for refunds already waiting under the old code. Nothing is deployed. A dev-server refund that is waiting when the worker upgrades may fail replay, which the README documents.
- No new `Step` value, and no use of `violation` for the timeout.
- No change to the API endpoint code. Its 404, 409 and 503 mapping already covers late approvals.
- No reminder or notification before the deadline. No extending the deadline.

## Implementation Approach

The timeout goes on the wait that already exists. When the wait raises a timeout, the action becomes `EscalateAction(reason=APPROVAL_TIMEOUT_CODE)` and the flow continues to `acting`. Leaving `awaiting_approval` makes the existing validator refuse most late approvals. The validator also gets a deadline check (`workflow.now() >= approval_deadline`). That covers an approval delivered together with the overdue timer, which the SDK runs before the timer. The deadline is computed once from `workflow.now()` and stored in the status before the step is entered.

## Critical Implementation Details

- **State sequencing: the deadline is enforced in the validator, not only by the timer.** The SDK runs Updates before timers in an activation. Suppose the worker is down when the deadline passes and an approval is queued meanwhile, because the API's Update RPC timed out but the server kept it. Then the overdue timer and the queued approval arrive in one activation, and the validator still sees `step == "awaiting_approval"`. A step-only check would accept the approval and refund after the deadline. `_refuse_unless_awaiting_approval` must also refuse when `workflow.now() >= self._status.approval_deadline`. `workflow.now()` is the activation time, which is never earlier than the timer's fire time. So "within 24 h" means `now < deadline`, and any approval in the same activation as the fired timer is refused.
- **After the wait, branch on the recorded approval, not on whether the timeout fired.** After catching `asyncio.TimeoutError`, decide from `self._status.approval`: escalate only when it is `None`. With the validator rule above, an accepted approval and a fired timer can't coexist, so this is a defensive check. It keeps "200 means honoured" true if the validator ever changes.
- **Timing: set `approval_deadline` before `_enter("awaiting_approval")`.** There is no yield in between, so any query that sees the step also sees the deadline. The clock starts when the wait starts, not when the ticket was submitted.

## Phase 1: Timeout in the workflow and status

### Overview

Bound the wait, escalate on expiry, expose the deadline, and prove it with time-skipped workflow tests.

### Changes Required:

#### 1. Deadline field in the status

**File**: `src/agentic_ticket_workflow/models.py`

**Intent**: Let an agent see how long a waiting refund has left.

**Contract**: `TicketStatus.approval_deadline: datetime | None = None`, with a short comment: set when a valid refund starts waiting, the time after which it is escalated instead.

#### 2. 24 h timeout on the approval wait

**File**: `src/agentic_ticket_workflow/workflow.py`

**Intent**: End an unanswered refund wait after 24 h with an escalation, and never refund without a recorded approval.

**Contract**:
- Module constants next to `REFUND_REJECTED`: `APPROVAL_TIMEOUT = timedelta(hours=24)` and `APPROVAL_TIMEOUT_CODE = "approval_timeout"`, each with a one-line comment.
- In the refund branch: `self._status.approval_deadline = workflow.now() + APPROVAL_TIMEOUT`, then `_enter("awaiting_approval")`, then `wait_condition(..., timeout=APPROVAL_TIMEOUT, timeout_summary=APPROVAL_TIMEOUT_CODE)` inside `try/except asyncio.TimeoutError`.
- After the wait: approval `None` → `action = EscalateAction(reason=APPROVAL_TIMEOUT_CODE)` and log `"refund approval timed out"` with `extra={"action": "escalate", "reason_code": APPROVAL_TIMEOUT_CODE}`. Rejected → close, as today. Approved → the refund, as today.
- `_refuse_unless_awaiting_approval` also refuses (same `ApplicationError`, type `not_awaiting_approval`) when `approval_deadline` is set and `workflow.now() >= approval_deadline` (see Critical Implementation Details). Both the validator and the handler go through it, as today.
- Replace the "(S-06 adds the 24 h timeout here.)" comment, and update the module docstring to mention the 24 h limit.
- `import asyncio` is allowed in workflow code (`asyncio.TimeoutError` is only an exception type).

#### 3. Workflow tests

**File**: `tests/test_workflow.py`

**Intent**: Cover FR-011(c), the late-approval refusal and the boundary.

**Contract**: four new tests, which reuse `started`, `fake_activities`, `wait_for_step` and `assert_refused`.

Time-skip rule: never skip time while `act` is running. A running activity stops automatic skipping, and an explicit skip past `act`'s 30 s `start_to_close_timeout` triggers retries. Skip only while the workflow is waiting, and only by the remaining time to the recorded deadline, never "24 h + a margin": `await env.sleep(status.approval_deadline - await env.get_current_time(handle))`. Pass `handle`: V2 test envs keep a clock per workflow, and V1 ignores it. Reaching the deadline fires the timer, because equality counts as expired.
- `test_unanswered_refund_is_escalated_after_24h`: T-2 with `T2_DECISION`. At `awaiting_approval`, assert `approval_deadline` is set. `await handle.result()` lets time skip. Assert steps `[..., awaiting_approval, acting, done]`, exactly one act call with `EscalateAction(reason="approval_timeout")` and key `ticket-T-2:escalate`, `approval is None`, `violation is None`, and that the `decision` still shows the refund proposal.
- `test_late_approval_is_refused_and_never_refunds`: act gated. At `awaiting_approval`, advance to the recorded `approval_deadline` with the remaining-duration sleep above (no extra margin while `act` will be gated), then `wait_for_step(handle, "acting")`, then `assert_refused` for both approve and reject. Then `gate.set()` promptly and get the result. Assert exactly one act call, the escalation, and `approval is None`.
- `test_approval_just_before_the_deadline_is_honoured`: at `awaiting_approval`, run `env.sleep(timedelta(hours=23, minutes=59))`, then approve, then get the result. Assert one act call with `T2_REFUND` and the approval recorded.
- `test_approval_queued_during_worker_downtime_after_the_deadline_is_refused` (regression for the validator deadline rule):
  1. Start T-2 on an explicit task queue and wait for `awaiting_approval`.
  2. Leave the worker context, so no worker is running.
  3. Send the approval as a background task (`asyncio.create_task(handle.execute_update(...))`). It stays pending on the server because no worker can run the validator.
  4. Advance to the recorded `approval_deadline` with the remaining-duration sleep, so the timer fires while no worker is running.
  5. Start a new worker on the **same** task queue. It receives the fired timer and the queued Update together.
  6. Assert the Update fails with `not_awaiting_approval`, exactly one act call with `EscalateAction(reason="approval_timeout")`, `approval is None`, and no refund.

  This needs a small helper (or a `task_queue` parameter on `started`), so two worker contexts can share one queue. If the test server delivers the Update in a separate activation, the test still holds, because the step has left `awaiting_approval`. Note in the test whether the same-activation order was observed: temporarily remove the new deadline check and confirm the test fails.

### Success Criteria:

#### Automated Verification:

- The new workflow tests pass: `uv run pytest tests/test_workflow.py`
- The whole suite passes, existing approval tests included: `uv run pytest`
- Lint and format pass: `uv run ruff check` and `uv run ruff format --check`

#### Manual Verification:

- In `docker compose up`, submit T-2. `GET /tickets/T-2` shows `approval_deadline` about 24 h ahead, and the Temporal UI shows a timer named `approval_timeout` on the workflow.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: HTTP late-approval test and README

### Overview

Prove the external contract end to end, and document the timeout.

### Changes Required:

#### 1. API test

**File**: `tests/test_api.py`

**Intent**: Show through the HTTP API that a timed-out refund escalates and a late approval gets 409.

**Contract**: `test_late_approval_through_the_api_is_refused`. Use `api_and_worker`, POST T-2 (202), and wait for `awaiting_approval`. Assert `approval_deadline` is present in the JSON. Skip time with `await env.client.get_workflow_handle("ticket-T-2").result()` (or `env.sleep`). Then `POST /tickets/T-2/approval {"approved": true}` → 409. `GET` shows `status == "completed"`, `result.action == {"type": "escalate", "reason": "approval_timeout"}`, and `"ticket-T-2:refund" not in acts.helpdesk.performed`.

#### 2. README

**File**: `README.md`

**Intent**: Replace the S-06 placeholder and describe the timeout behaviour and its limitation.

**Contract**:
- Line 85: the wait is bounded by 24 h from entering `awaiting_approval`. It is a durable Temporal timer, so the deadline survives restarts. On expiry the ticket escalates with `approval_timeout`. An approval counts only if the workflow processes it before the deadline (`now < deadline`). One processed at or after it, including one queued while the worker was down, gets 409. An approval accepted before the deadline is always honoured.
- Line 53: add "its 24 h approval wait ran out" to the 409 cases.
- In the approve-a-refund example, mention `approval_deadline` in the waiting status.
- Limitations: the deadline is fixed at 24 h. Adding the timer is a nondeterministic change, so a refund already waiting under the previous code (local dev server only) may fail replay after upgrading. Reset the dev server with `docker compose down -v`. It **deletes all local ticket histories** (the `temporal-data` volume); a plain `down` keeps them.
- Approvals: an approval that reaches the workflow at or after the deadline is refused, even one queued while the worker was down.

### Success Criteria:

#### Automated Verification:

- The API test passes: `uv run pytest tests/test_api.py`
- The whole suite passes: `uv run pytest`
- Lint and format pass: `uv run ruff check` and `uv run ruff format --check`

#### Manual Verification:

- The README sections read correctly, and no text still says the timeout is deferred to S-06.

---

## Testing Strategy

### Unit Tests:

- None new. The rule checks (`rules.py`) are unchanged.

### Integration Tests:

- Time-skipped workflow tests: timeout escalation (FR-011 c), late approval refused while acting, approval at 23 h 59 m honoured, and an approval queued during worker downtime past the deadline refused.
- An HTTP test: timed-out T-2 → 409 on approval, escalated, no refund.

### Manual Testing Steps:

1. `docker compose up`, then `POST /tickets` with T-2.
2. `GET /tickets/T-2` shows `step: awaiting_approval` and `approval_deadline` ≈ now + 24 h.
3. The Temporal UI shows the `approval_timeout` timer pending on `ticket-T-2`.

## Performance Considerations

None. There is one timer per waiting refund.

## Migration Notes

There is no versioning (see What We're NOT Doing). A refund already waiting in a running local dev server when the new worker starts may hit a nondeterminism error. Workflow histories live in the named `temporal-data` volume, so a plain `docker compose down` keeps them. Reset with `docker compose down -v`, then `up`. That deletes **all** local ticket histories.

## References

- Roadmap: `context/foundation/roadmap.md` S-06
- Prior slice: `context/archive/2026-11-07-refund-approved-or-rejected/plan.md` (it deferred the timeout to this slice)
- PRD: `context/foundation/prd.md` US-04 (line 94), FR-006 (line 121), FR-011 (line 135), NFR restart (line 161)
- The wait being changed: `src/agentic_ticket_workflow/workflow.py`, `run`, refund branch

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Timeout in the workflow and status

#### Automated

- [x] 1.1 The new workflow tests pass: `uv run pytest tests/test_workflow.py` — b3c709a
- [x] 1.2 The whole suite passes, existing approval tests included: `uv run pytest` — b3c709a
- [x] 1.3 Lint and format pass: `uv run ruff check` and `uv run ruff format --check` — b3c709a

#### Manual

- [x] 1.4 In compose, T-2 shows `approval_deadline` about 24 h ahead, and the Temporal UI shows the `approval_timeout` timer — b3c709a

### Phase 2: HTTP late-approval test and README

#### Automated

- [x] 2.1 The API test passes: `uv run pytest tests/test_api.py` — 9807912
- [x] 2.2 The whole suite passes: `uv run pytest` — 9807912
- [x] 2.3 Lint and format pass: `uv run ruff check` and `uv run ruff format --check` — 9807912

#### Manual

- [x] 2.4 The README sections read correctly, and no text still says the timeout is deferred to S-06 — 9807912
