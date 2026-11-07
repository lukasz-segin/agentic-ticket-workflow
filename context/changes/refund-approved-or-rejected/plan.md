# Refund Approved or Rejected Implementation Plan

## Overview

Roadmap S-05 (US-02, FR-006, FR-007, FR-011 b). A refund that passes every rule no longer gets the placeholder escalation `refund_needs_approval`. Instead the ticket waits at a new `awaiting_approval` step with the proposed refund visible. A person resolves it through `POST /tickets/{ticket_id}/approval`. On approve, the checked refund is issued exactly once, even when the helpdesk fails at random. On reject, the ticket closes with no refund and a reason that quotes the approver's comment. The optional approver name and comment are kept on the ticket. An approval for an unknown ticket is refused with 404, and one for a ticket that isn't waiting is refused with 409, before anything reaches the workflow.

## Current State Analysis

- `workflow.py:122-125`: a valid refund is replaced by `EscalateAction(reason="refund_needs_approval")`. That marks the spot this slice changes.
- `workflow.py:132`: the act idempotency key is `f"{workflow_id}:{action.type}"`. An approved refund therefore uses `ticket-T-2:refund` and a rejection uses `ticket-T-2:close`. `FakeHelpdesk` (`helpdesk.py:21-36`) dedupes on that key, and `ACT_RETRY` (5 attempts) covers temporary failures. Exactly-once needs no new mechanism.
- `models.py:15`: `Step` is a Literal and needs a new value. `TicketStatus` (`models.py:95-104`) has no approval field yet.
- `api.py`: holds `POST /tickets` and `GET /tickets/{id}`, with `describe()`-based 404 and `_temporal_unavailable` for 503. It has no approval endpoint yet. The path is fixed by tech-stack.md:31: `POST /tickets/{ticket_id}/approval`.
- shape-notes.md:279 (user design note): the 404/409 rule is enforced by a **Temporal Update validator**, so a late approval is rejected before it reaches the workflow.
- `logs.py:22-32`: `ALLOWED_EXTRAS` is an allow-list. A new log field has to be added there or it is dropped.
- Tests asserting the placeholder: `tests/test_workflow.py:84-95` (`test_refund_is_escalated_until_approval_exists`) and `:230-235` (`test_t2_valid_refund_is_held_for_approval_through_the_real_activities`).
- README: `:61` describes the placeholder. `:98` says the Temporal UI "can send signals (approvals)", but approvals will be Updates.

## Desired End State

- T-2 through the real activities stops at `step == "awaiting_approval"` with `decision.action == RefundAction(INV-1002, 49.0)`, no `result`, and Temporal status `running`.
- `POST /tickets/T-2/approval {"approved": true, "approver": "Ann", "comment": "ok"}` returns 200 `{"ticket_id": "T-2", "workflow_id": "ticket-T-2", "approved": true}` as soon as the approval is recorded. The workflow then acts. `GET` eventually shows `step == "done"`, `result.action == RefundAction(INV-1002, 49.0)` and `approval == {approved: true, approver: "Ann", comment: "ok"}`. Exactly one refund is performed, even with helpdesk failures.
- Rejecting closes the ticket with `CloseAction(reason="refund_rejected: <comment>")`, or `reason="refund_rejected"` when there is no comment. No refund is performed.
- A second approval or rejection, an approval for a non-refund or rule-breaking ticket (T-1, T-6), an approval while the ticket is still deciding, and an approval for a finished ticket all get 409. An unknown ticket ID gets 404, and a malformed body or ID gets 422.
- Each approval writes one log line with `approved` (bool) and `approver` (capped string). The comment is never logged.
- `uv run pytest`, `uv run ruff check` and `uv run ruff format --check` pass.

### Key Discoveries:

- Python SDK ordering (`worker/_workflow_instance.py:676-745`, `_apply_do_update`): each Update runs its validator and then its handler inside one task. A **synchronous** handler is called with no `await` in between, so for a sync handler, validate-plus-write is atomic with respect to other Updates. Handlers interleave only at an `await` (async handlers). The handler still re-checks "still waiting" as a defensive guard, so the guarantee doesn't silently depend on the handler staying sync (see Critical Implementation Details).
- An Update sent to a closed workflow fails at the RPC level, not in the validator. The API therefore checks `describe()` first (missing → 404, not running → 409). It also maps the race where the workflow closes between `describe()` and the update to 409.
- `temporalio` 1.35.0 provides `@workflow.update`, `@<handler>.validator`, `WorkflowHandle.execute_update(..., rpc_timeout=...)`, `WorkflowUpdateFailedError` and `WorkflowUpdateRPCTimeoutOrCancelledError` (`client/_exceptions.py:73`).

## What We're NOT Doing

- **The 24 h timeout and escalation (S-06).** The wait in this slice has no timeout. S-06 adds `timeout=24h` to this same wait, plus its required test. Until then an unanswered refund waits forever. That is acceptable mid-milestone.
- Logging the approver's comment. It is free text that may quote the ticket. It lives only in the ticket status (Temporal history). This deviates on purpose from the PRD Access Control wording "name and comment in the logs" (user decision). The README says so.
- Changing the refund amount or invoice at approval time. A person approves or rejects exactly the checked proposal.
- Treating a repeated identical approval as idempotent success. Per FR-006, "already approved or rejected" is a 409.
- Accepting approvals as signals (for example from the Temporal UI's signal button). A signal would bypass the validator.
- Auth or verified approvers (PRD Access Control, a known limitation).
- Re-running the rule check at approval time. The decision and the invoice data are immutable.

## Implementation Approach

Approvals are a Temporal Update on `TicketWorkflow` (shape-notes design note). The validator refuses with 409 before the update is written to history. The handler only records the approval, and the workflow's main coroutine, blocked on `wait_condition`, takes it from there. So the HTTP call returns as soon as the approval is recorded and never waits on helpdesk retries (user decision). The refund or close then goes through the existing `act` activity, retries and idempotency key unchanged. The API stays a thin translator from Temporal outcomes to HTTP codes.

## Critical Implementation Details

- **State sequencing: "first approval wins".** The validator refuses unless `step == "awaiting_approval"` and no approval is recorded yet. Keep the handler synchronous (`def`, no `await`). The SDK then runs validator and handler back to back with no yield, so the check and the write can't interleave with another Update. The handler still repeats the check and raises the same `ApplicationError` before setting `self._status.approval`. That defensive guard keeps the guarantee if someone later makes the handler async. Without it, an async handler could tell two callers yes. Only one refund would still go out.
- **Timing: the step changes before the wait.** Enter `awaiting_approval` (and log it) *before* `await workflow.wait_condition(...)`, so the validator sees the waiting state as soon as the wait starts. The main coroutine, not the handler, moves the step on to `acting`.

## Phase 1: Workflow Approval Wait

### Overview

The workflow waits for a validated approval Update after a valid refund decision, then acts on the refund or closes the ticket. The status and logs carry the approval.

### Changes Required:

#### 1. Domain types

**File**: `src/agentic_ticket_workflow/models.py`

**Intent**: Add the approval request and status types and the new step.

**Contract**:
- `Step` gains `"awaiting_approval"`, placed between `"checking"` and `"acting"` in the comment and in the narrative.
- `class Approval(BaseModel)` holds `approved: bool`, `approver: str | None = None` (1–100 chars) and `comment: str | None = None` (1–1000 chars). The explicit `= None` defaults matter: without them Pydantic makes both fields required, and a bare `{"approved": true}` would get a 422. It is the Update argument, the API request body and the status field, so one type covers all three. Bounded because it is stored in history and `approver` is logged.
- `TicketStatus` gains `approval: Approval | None = None`.
- Remove the stale "Later slices add values" comment on `Step` if it no longer fits. S-06 does not add a step.

#### 2. Workflow wait and Update

**File**: `src/agentic_ticket_workflow/workflow.py`

**Intent**: Replace the `refund_needs_approval` placeholder with the wait, and add the `approve` Update with its validator.

**Contract**:
- Module constants: `NOT_AWAITING_APPROVAL = "not_awaiting_approval"` (the `ApplicationError` type both the validator and the handler raise, which the API maps to 409) and `REFUND_REJECTED = "refund_rejected"`.
- In `run`, for a refund with no violation: `_enter("awaiting_approval")`, log `"refund awaiting approval"`, then `await workflow.wait_condition(lambda: self._status.approval is not None)`. Approved → `action = decided.decision.action` (the checked `RefundAction`). Rejected → `action = CloseAction(reason=f"{REFUND_REJECTED}: {comment}" if comment else REFUND_REJECTED)`. Everything after that goes through the existing `acting` path, so the idempotency key becomes `…:refund` or `…:close`.
- `@workflow.update def approve(self, approval: Approval) -> None` with an `@approve.validator`. Both raise `ApplicationError("ticket is not awaiting approval", type=NOT_AWAITING_APPROVAL, non_retryable=True)` unless the status is at `awaiting_approval` with `approval is None`. The handler re-checks before writing (see Critical Implementation Details). After writing, it logs `"refund approval received"` with `extra={"approved": ..., "approver": ...}`. It never logs the comment.
- Update the module docstring to mention the approval wait.

#### 3. Log allow-list

**File**: `src/agentic_ticket_workflow/logs.py`

**Intent**: Let the approval audit fields through, and correct the stale example in the comment.

**Contract**: `ALLOWED_EXTRAS` gains `"approved"` (bool) and `"approver"` (approver-written name, capped at 100 chars, JSON-escaped like every value). Update the comment block: `approver` is the one free-text field allowed, by user decision, as an audit trail, and the comment stays out. Replace the `refund_needs_approval` example in the `reason_code` comment with a current code (e.g. `refund_amount_above_invoice`).

#### 4. Workflow tests

**File**: `tests/test_workflow.py`

**Intent**: Replace the two placeholder tests and cover approve, reject, and the refusal paths. This is FR-011 (b).

**Contract**: `run_ticket` waits for completion, so it doesn't fit a run that pauses for approval. Add a small helper that starts the workflow and waits until the queried step is `awaiting_approval`, so tests can send `handle.execute_update(TicketWorkflow.approve, Approval(...))`. Tests:
- Move `ScriptedRandom` from `tests/test_helpdesk.py:13` into a shared `tests/fakes.py` and import it in both test files.
- `test_approved_refund_is_issued_exactly_once_despite_helpdesk_failures`: real `TicketActivities(FakeChatModel(), FakeHelpdesk(0.5, rng=ScriptedRandom([0.0, 0.9, 0.9])))` with T-2. The script follows `test_helpdesk.py:37-45`. On attempt 1 the refund is **recorded and then the response is lost** ("after recording" branch). Attempt 2 is a Temporal retry that meets the known key and returns the recorded result. This exercises the dedupe path, not just a pre-recording retry. Before approval, assert `step == "awaiting_approval"`, the visible `RefundAction(INV-1002, 49.0)` and `result is None`. Then approve with a name and comment. Final status: `steps == [received, deciding, checking, awaiting_approval, acting, done]`, `result.action` is the refund, `result.helpdesk_ref == "HD-1"` and `approval` is kept. Helpdesk: `performed` has exactly one key, `ticket-T-2:refund`, and the script is fully consumed (both attempts happened). Uses time skipping.
- `test_concurrent_approve_and_reject_accept_exactly_one`: with T-2 waiting, send an approve and a reject at once (`asyncio.gather(..., return_exceptions=True)`). Exactly one succeeds and the other raises `WorkflowUpdateFailedError` with type `not_awaiting_approval`. The final status `approval.approved` matches the winner, and exactly one act call follows (refund or close, never both).
- `test_rejected_refund_closes_with_the_comment` (parametrize comment / no comment): fake act, so exactly one act call with `CloseAction(reason="refund_rejected: <c>")` or `CloseAction(reason="refund_rejected")`, key `ticket-T-2:close`, and no refund call.
- `test_second_approval_is_refused`: after the first approval is accepted, a second `execute_update` raises `WorkflowUpdateFailedError` whose cause type is `not_awaiting_approval`. Use a fake act that blocks until released, so the workflow is still running at `acting` when the second approval arrives.
- `test_approval_for_a_ticket_not_awaiting_is_refused`: T-1 reply (with an act that blocks, so the workflow is still running) → `WorkflowUpdateFailedError`, type `not_awaiting_approval`.
- Update `test_t6_…` or add an assertion that T-6 never enters `awaiting_approval`: `"awaiting_approval" not in status.steps`.

### Success Criteria:

#### Automated Verification:

- Workflow tests pass: `uv run pytest tests/test_workflow.py`
- Full suite passes: `uv run pytest`
- Lint and format pass: `uv run ruff check` and `uv run ruff format --check`
- No placeholder left in code or tests: `grep -rn refund_needs_approval src tests` returns nothing

#### Manual Verification:

- Read the approved-refund test and confirm its script loses the response *after* the refund is recorded, and the retry returns the same `HD-1` with exactly one refund performed

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Approval Endpoint and README

### Overview

Expose the Update over HTTP with the FR-006 status codes, and update the README for the new flow.

### Changes Required:

#### 1. Approval endpoint

**File**: `src/agentic_ticket_workflow/api.py`

**Intent**: Add `POST /tickets/{ticket_id}/approval`, which translates Temporal outcomes to 200/404/409/503.

**Contract**:
- Request body `Approval`. Path `ticket_id` uses `Path(pattern=IDENTIFIER_PATTERN)`, as in `get_ticket`. Response model `ApprovalResponse(ticket_id, workflow_id, approved)`, status 200.
- Flow: `handle.describe(rpc_timeout=5s)`. RPC `NOT_FOUND` → 404. `_UNAVAILABLE` → 503. A status other than `RUNNING` → 409. Then `handle.execute_update(TicketWorkflow.approve, approval, rpc_timeout=5s)`. `WorkflowUpdateFailedError` whose cause is an `ApplicationError` of type `not_awaiting_approval` → 409, and any other cause is re-raised. An `RPCError` with `NOT_FOUND` or `FAILED_PRECONDITION` (the workflow closed between describe and update) → 409. `WorkflowUpdateRPCTimeoutOrCancelledError` (no worker) and `_UNAVAILABLE` → 503.
- Log one line per outcome with `_ids(...)`: `"approval recorded"` with `approved` and `approver`, `"approval refused"` with `reason_code="not_awaiting_approval"`, and `"ticket not found"` for the 404. Never the comment.

#### 2. API test

**File**: `tests/test_api.py`

**Intent**: Cover the external interface for approvals: one end-to-end path plus the refusals.

**Contract**: `test_approve_t2_through_the_api`, using real activities with `FakeHelpdesk(0.0)`. Submit T-2, then poll `GET` until `step == "awaiting_approval"` and assert the proposed refund is visible. Approve → 200 with the body above. A second approval → 409. Wait for the result, then `GET` shows `done`, the refund result and the kept `approval`. Exactly one refund is performed. In the same or a sibling test: an approval for unknown `NOPE` → 404; an approval for a finished T-1 → 409 (this exercises only the `describe()`-not-running branch); a malformed body (e.g. `approved` missing) → 422. A minimal body `{"approved": false}` with no approver or comment is accepted (200) on a second waiting refund ticket.

Update-stage errors can't be produced reliably against the real server, so cover them with a stub client. Its `describe()` returns `status = WorkflowExecutionStatus.RUNNING`, and its `execute_update` raises a parametrized error. `RPCError(NOT_FOUND)` → 409, `RPCError(FAILED_PRECONDITION)` → 409, `WorkflowUpdateFailedError(ApplicationError(type="not_awaiting_approval"))` → 409, `WorkflowUpdateRPCTimeoutOrCancelledError()` → 503, `RPCError(UNAVAILABLE)` → 503. Both exception constructors are public (`client/_exceptions.py`). Extend `_UnavailableClient` so the approval endpoint also returns 503 at the `describe()` stage.

#### 3. README

**File**: `README.md`

**Intent**: Keep the README true as the service is built (FR-012 is finished in S-09).

**Contract**:
- `:61`: replace the placeholder sentence. A valid refund now waits at `awaiting_approval` for `POST /tickets/{id}/approval`. Approve issues it exactly once, and reject closes the ticket with `refund_rejected[: comment]`. Note that the 24 h timeout arrives with S-06; until then the wait is unbounded.
- "Run locally": add a T-2 example. Submit, then `GET` showing `awaiting_approval`, then `curl -X POST localhost:8000/tickets/T-2/approval -d '{"approved": true, "approver": "Ann", "comment": "duplicate confirmed"}'`, plus the 404/409 meaning in one line.
- `:98`: "can send signals (approvals)" → approvals are Temporal Updates. Keep the point that the UI must stay internal.
- Known limitations: the approver name is logged unverified, and the comment is kept only in the ticket status, not in the logs.

### Success Criteria:

#### Automated Verification:

- API tests pass: `uv run pytest tests/test_api.py`
- Full suite passes: `uv run pytest`
- Lint and format pass: `uv run ruff check` and `uv run ruff format --check`

#### Manual Verification:

- `docker compose up`: submit T-2 and see `awaiting_approval` with the INV-1002 / 49.0 refund. Approve it, then see `done` with the refund `helpdesk_ref` in `GET`. With the default 30% failure rate, the worker logs show only one `helpdesk action done` for the refund.
- Approve T-2 again → 409. Approve `NOPE` → 404. Approve T-1 → 409.
- Submit a fresh refund ticket (a new ID with T-2's text), reject it with a comment, and see `CloseAction(reason="refund_rejected: …")` and no refund.
- The worker and API log lines for the approval carry `ticket_id`, `workflow_id`, `approved` and `approver`, and no comment text.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Testing Strategy

### Unit Tests:

- No new business rules. `rules.py` is unchanged, and the approval state check lives in the workflow because it depends on workflow state.

### Integration Tests:

- Workflow with time skipping: approved, with the helpdesk losing the response after recording the refund (FR-011 b); rejected with and without a comment; a second approval refused; concurrent approve and reject with exactly one accepted; an approval for a non-refund ticket refused; T-6 never waits.
- HTTP: approve 200, then a repeat 409. Minimal body accepted. Unknown 404, finished-ticket 409, bad body 422, Temporal down 503. A stub client covers the Update-stage errors: closed in between (`NOT_FOUND`/`FAILED_PRECONDITION`) → 409, no worker (`WorkflowUpdateRPCTimeoutOrCancelledError`) → 503.

### Manual Testing Steps:

1. `docker compose up`, submit T-2, check `GET /tickets/T-2` shows `awaiting_approval`.
2. Approve, poll until `done`, confirm a single refund `helpdesk_ref` and one refund log line.
3. Repeat the approval (409), approve an unknown ID (404) and approve T-1 (409).
4. Reject a fresh refund ticket with a comment and check the close reason.

## Performance Considerations

None. The wait is a durable timer-free condition. It costs nothing while idle.

## Migration Notes

The workflow code changes the command sequence for refund tickets. Any refund workflow started on the old code and still open when the new worker picks it up would fail replay (a nondeterminism error). Old refunds don't necessarily complete at once: their `act` can still be retrying the helpdesk. Also, `docker compose down` keeps the `temporal-data` volume (`docker-compose.yml:32-35`), so old executions survive it. Before running the new worker locally, do one of these:
- Wait until no old execution is open (`GET` shows `completed`/`failed`, or check the Temporal UI).
- Wipe Temporal state with `docker compose down -v`.
- Run under a separate Compose project (`docker compose -p s05 up`), which gets its own volume.

This is local only: nothing is deployed, and the README's Azure section already requires single-revision workers (`README.md:120`).

## References

- PRD: `context/foundation/prd.md` (US-02, FR-006, FR-007, FR-011, Access Control, Business Logic edge cases)
- Roadmap: `context/foundation/roadmap.md` S-05 (and S-06 for the deferred timeout)
- Design note: `context/foundation/shape-notes.md:279` (Update validator)
- Placeholder to replace: `src/agentic_ticket_workflow/workflow.py:122-125`
- Idempotency key: `src/agentic_ticket_workflow/workflow.py:132`, `src/agentic_ticket_workflow/helpdesk.py:21-36`
- Lesson: `context/foundation/lessons.md` ("Ticket text hides in derived payloads")

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Workflow Approval Wait

#### Automated

- [x] 1.1 Workflow tests pass: `uv run pytest tests/test_workflow.py` — 3446387
- [x] 1.2 Full suite passes: `uv run pytest` — 3446387
- [x] 1.3 Lint and format pass: `uv run ruff check` and `uv run ruff format --check` — 3446387
- [x] 1.4 No placeholder left in code or tests: `grep -rn refund_needs_approval src tests` returns nothing — 3446387

#### Manual

- [x] 1.5 Approved-refund test loses the response after recording, and the retry returns the same `HD-1` with exactly one refund — 3446387

### Phase 2: Approval Endpoint and README

#### Automated

- [x] 2.1 API tests pass: `uv run pytest tests/test_api.py`
- [x] 2.2 Full suite passes: `uv run pytest`
- [x] 2.3 Lint and format pass: `uv run ruff check` and `uv run ruff format --check`

#### Manual

- [x] 2.4 Compose: T-2 waits, approve → `done` with one refund despite 30% failures
- [x] 2.5 Compose: repeat approval 409, unknown 404, T-1 409
- [x] 2.6 Compose: rejecting a fresh refund ticket closes it with `refund_rejected: …` and no refund
- [x] 2.7 Approval log lines carry IDs, `approved` and `approver`, and no comment text
