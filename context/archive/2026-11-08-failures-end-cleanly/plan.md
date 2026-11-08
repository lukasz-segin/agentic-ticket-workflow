# Failures End Cleanly Implementation Plan

## Overview

This is roadmap slice S-07 (FR-007, FR-008, FR-011 d). Every ticket reaches a final state with a clear reason when the outside services misbehave:

- A model answer that is still unreadable after the decide retries escalates with `unreadable_model_answer`. This includes a tool loop that overruns its step limit.
- A model that is still unavailable after its retry limit escalates with `llm_unavailable`. This includes a call that hangs until it times out.
- A helpdesk that is still failing after its last retry fails the ticket with `helpdesk_unavailable`. `GET /tickets/{id}` and the logs show that reason.
- A worker restart in the middle of an action loses no ticket and repeats no action.

## Current State Analysis

- `src/agentic_ticket_workflow/agent.py` raises `UnreadableModelAnswer` for an unparseable decision, a bad tool call, and `no decision within {max_steps} steps`. No exception means "the model is unavailable". The `ChatModel` protocol says nothing about errors.
- `src/agentic_ticket_workflow/activities.py` `decide` catches only `UnknownCustomer` and `DisallowedValue`, which become non-retryable `ApplicationError`s with the reason code as `type`. `UnreadableModelAnswer` escapes as a generic error, so the SDK wraps it as `ApplicationError(type="UnreadableModelAnswer")`. It is retried by `DECIDE_RETRY` (3 attempts).
- `src/agentic_ticket_workflow/workflow.py:101-104` escalates only when the `ActivityError` cause's type is in `ESCALATE_ON_ERROR` (`unknown_customer` + the allowed-value codes). Anything else, including an exhausted unreadable answer or a timeout, re-raises and fails the workflow.
- `workflow.py:163-173`: when `act` exhausts `ACT_RETRY` (5 attempts, backoff capped at 10 s), the `ActivityError` propagates unhandled. The workflow fails, but `TicketStatus` has no reason, the step stays `acting`, and no log line carries `helpdesk_unavailable`. `README.md:181` already describes an alert on that code.
- `src/agentic_ticket_workflow/api.py:132-144` reads a COMPLETED ticket from the result. Any other execution status is read through the `status` query, which also works for a FAILED execution while a worker is running.
- FR-011 (d) is already covered by `tests/test_workflow.py` `test_approved_refund_is_issued_exactly_once_despite_helpdesk_failures`: a scripted helpdesk fails, then a retry succeeds, under time skipping.
- Test patterns: `tests/test_workflow.py` has `fake_activities`, `started`, `worker`, `wait_for_step` and `AsapModel`. The real-activity tests build `TicketActivities(model, FakeHelpdesk(rate))`. The worker-downtime test (`test_workflow.py:301`) restarts a worker on a shared task queue with `max_cached_workflows=0`. `tests/test_agent.py` has `AlwaysToolModel` and `NotJsonModel`. `tests/test_api.py` `api_and_worker` hard-codes `FakeHelpdesk(0.0)`.

## Desired End State

- `decide` raises `ApplicationError(type="unreadable_model_answer")` (retryable) for an `UnreadableModelAnswer`, and `ApplicationError(type="llm_unavailable")` (retryable) for an `agent.ModelUnavailable`. Messages are fixed text and causes are dropped (`from None`).
- After `DECIDE_RETRY` runs out, the workflow escalates:
  - with `unreadable_model_answer` or `llm_unavailable`, taken from the last attempt's `ApplicationError` type;
  - with `llm_unavailable` when the last attempt timed out (`temporalio.exceptions.TimeoutError`).

  The steps are `[received, deciding, acting, done]`, `decision` is `None` and `violation` is `None`.
- Any other `decide` failure (a code bug) still fails the workflow, as today.
- Any `ActivityError` from `act` puts the ticket in a new `failed` step, sets `failure_reason="helpdesk_unavailable"`, logs `reason_code: helpdesk_unavailable`, and fails the workflow with `ApplicationError(type="helpdesk_unavailable", non_retryable=True)`. `GET /tickets/{id}` shows `status: failed`, `step: failed`, `failure_reason: helpdesk_unavailable`.
- A worker stopped while `act` is in flight, after the helpdesk recorded the action, is replaced by a new worker. The new worker finishes the ticket, and the helpdesk performed the action exactly once.
- The production `FakeChatModel` is unchanged. LLM failures are simulated only by test doubles.
- `uv run pytest`, `uv run ruff check` and `uv run ruff format --check` pass.

### Key Discoveries:

- The workflow sees `ActivityError` only after the retry policy stops, and `err.cause` is the **last** attempt's failure. Retryable and non-retryable codes can therefore share `ESCALATE_ON_ERROR`. Mixed attempts are classified by the last one: for example, two unreadable answers followed by a timeout escalate as `llm_unavailable`.
- `temporalio.exceptions.TimeoutError` (exceptions.py:244) is not the builtin `TimeoutError`. `workflow.py:146` already uses the builtin `TimeoutError` for `wait_condition`, so the Temporal one must be imported under an alias.
- `logs.py` already allow-lists `reason_code` and `error_type`. No formatter change is needed.
- Lesson "Ticket text hides in derived payloads": exceptions raised from model output or provider errors use `from None` and fixed messages. Logs carry only the code and the exception type name.

## What We're NOT Doing

- No change to the production fake model, and no `LLM_FAILURE_RATE` or keyword trigger. A reviewer can't trigger the LLM escalations in `docker compose up`; the README points to the tests. `HELPDESK_FAILURE_RATE=1.0` already demos `helpdesk_unavailable`.
- No configurable retry limits. `DECIDE_RETRY` (3) and `ACT_RETRY` (5) stay constants and the README states them.
- No mapping of unexpected `decide` exceptions (code bugs) or `check` failures to a reason code. They still fail the workflow without one (accepted tradeoff).
- No escalation fallback when the helpdesk is down (PRD FR-007).
- No persistent helpdesk idempotency store. Keys are lost on a real worker process restart, which stays a README known limitation.
- No real provider error mapping. S-08 maps its SDK errors to `agent.ModelUnavailable`.
- No `workflow.patched()` versioning for the new `failed` branch. Nothing is deployed (same stance as S-06).

## Implementation Approach

The activity classifies each error once, by reason code in `ApplicationError.type`, and keeps it retryable when a retry might help. The workflow maps a code to an escalation only after the retry policy has given up. A failed helpdesk action is recorded in the status before the workflow fails, so the existing query path in the API shows it with no API changes.

## Critical Implementation Details

- **State sequencing on helpdesk failure:** set `failure_reason`, enter `failed`, then log, and only then raise the workflow `ApplicationError`. The status the query replays must already hold the reason. Raise an `ApplicationError` (a `FailureError`), never a plain exception: a plain exception fails only the workflow *task*, and Temporal retries that forever.
- **Restart test plumbing:** stop the first worker with its workflow cache disabled (`max_cached_workflows=0`). Otherwise the test server keeps routing workflow tasks to the dead worker's sticky queue. The in-flight `act` attempt must wait with `await` (an `asyncio.Event`), never by blocking inside the synchronous `FakeHelpdesk.perform`, which `TicketActivities.act` calls directly on the event loop (`activities.py:43`). On shutdown the attempt is cancelled (`graceful_shutdown_timeout` defaults to 0). Then either the failure is reported or the 30 s start-to-close timeout expires under time skipping, and the server schedules attempt 2 for the second worker.

## Phase 1: Model failures escalate

### Overview

Classify unreadable and unavailable model errors in the decide activity, and escalate on them (and on decide timeouts) once retries run out.

### Changes Required:

#### 1. Model-unavailable exception

**File**: `src/agentic_ticket_workflow/agent.py`

**Intent**: Give `ChatModel` implementations a declared way to say "the provider is down or unreachable", separate from an unusable answer.

**Contract**: add `class ModelUnavailable(Exception)`. The `ChatModel.complete` docstring says implementations raise it for provider, network and rate-limit errors. `decide()` lets it propagate unchanged.

#### 2. Decide activity classification

**File**: `src/agentic_ticket_workflow/activities.py`

**Intent**: Turn `UnreadableModelAnswer` and `ModelUnavailable` into retryable `ApplicationError`s whose `type` is the reason code, with a log line per attempt.

**Contract**:
- `UnreadableModelAnswer` → `ApplicationError("model answer unreadable", type=UNREADABLE_MODEL_ANSWER) from None`. Not `non_retryable`.
- `ModelUnavailable` → `ApplicationError("model unavailable", type=LLM_UNAVAILABLE) from None`. Not `non_retryable`.
- Each logs with `reason_code` only. The `ModelUnavailable` path also logs `error_type`, the provider exception's class name. No messages.

#### 3. Workflow escalation mapping

**File**: `src/agentic_ticket_workflow/workflow.py`

**Intent**: After `DECIDE_RETRY` gives up, escalate on the two new codes, and on a final timeout as `llm_unavailable`.

**Contract**:
- New constants `UNREADABLE_MODEL_ANSWER = "unreadable_model_answer"` and `LLM_UNAVAILABLE = "llm_unavailable"`, both added to `ESCALATE_ON_ERROR`. Update the comment, which no longer reads "S-07 adds more".
- In the `except ActivityError` branch, the code is `LLM_UNAVAILABLE` when `err.cause` is `temporalio.exceptions.TimeoutError` (imported under an alias, e.g. `ActivityTimeoutError`). Otherwise it is the `ApplicationError` type, as today.
- `violation` is set only for allowed-value codes, as today.

#### 4. Tests

**Files**: `tests/test_workflow.py`, `tests/test_agent.py` (or a new `tests/test_activities.py`)

**Intent**: Prove each model failure ends as the right escalation after the right number of attempts, through the real `decide` activity where possible.

**Contract**:
- Workflow tests through `TicketActivities(model, FakeHelpdesk(0.0))`, with call-counting test-only models:
  - a model that always returns non-JSON → `model.calls == 3`, then `EscalateAction(reason="unreadable_model_answer")`, with `decision is None` and `violation is None`;
  - a model that always requests a tool (step-limit overrun) → escalated with `unreadable_model_answer`;
  - a model that raises `ModelUnavailable` → 3 calls, escalated with `llm_unavailable`.
- A workflow test where a fake `decide` blocks past its 60 s start-to-close timeout on every attempt, driven by `env.sleep`, ends escalated with `llm_unavailable`. If the time-skipping server can't time out an in-flight activity this way, move the cause-to-code mapping into a small function in `workflow.py`. Then unit-test it with a constructed `ActivityError` whose cause is a `TimeoutError`, and record the swap in the PR.
- An activity unit test (`temporalio.testing.ActivityEnvironment`) checks both new `ApplicationError`s: their `type`, `non_retryable is False`, and a message containing no model text.
- `test_unlisted_activity_error_still_fails_the_workflow` stays green, unchanged.

#### 5. README

**File**: `README.md`

**Intent**: Document the two new escalation reasons, the decide retry limit (3 attempts) and the timeout mapping. Say that the fake model never fails and the tests simulate failures.

**Contract**: one short subsection near "Decision rules", listing reason codes `unknown_customer`, `unreadable_model_answer` and `llm_unavailable`.

### Success Criteria:

#### Automated Verification:

- New model-failure workflow and activity tests pass: `uv run pytest tests/test_workflow.py tests/test_agent.py`
- Full suite passes: `uv run pytest`
- Lint passes: `uv run ruff check`
- Format passes: `uv run ruff format --check`

#### Manual Verification:

- Temporal UI for a test-run ticket shows three `decide` attempts, then an `act` with the escalation (checked once in a local run with a temporary junk model, or by reading the test history)

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Helpdesk exhaustion fails cleanly

### Overview

Record `helpdesk_unavailable` in the status and logs, fail the workflow with that type, show it through the API, and prove a mid-action restart repeats nothing.

### Changes Required:

#### 1. Status model

**File**: `src/agentic_ticket_workflow/models.py`

**Intent**: Let a failed ticket say why, and make its step stop reading as "acting".

**Contract**: `Step` gains `"failed"`. `TicketStatus.failure_reason: str | None = None`, documented as "set when the ticket fails (FR-007), e.g. `helpdesk_unavailable`".

#### 2. Workflow failure path

**File**: `src/agentic_ticket_workflow/workflow.py`

**Intent**: Turn any `act` failure into a clean, explained workflow failure.

**Contract**:
- New constant `HELPDESK_UNAVAILABLE = "helpdesk_unavailable"`.
- Wrap the `act` call in `except ActivityError as err:`. Set `self._status.failure_reason`, call `self._enter("failed")`, log `"ticket failed"` with `action` and `reason_code`, then `raise ApplicationError("helpdesk unavailable", type=HELPDESK_UNAVAILABLE, non_retryable=True) from err`. The cause chain holds only fixed helpdesk messages.

#### 3. API

**File**: `src/agentic_ticket_workflow/api.py`

**Intent**: No logic change is expected, because a FAILED execution already goes through the query path. Touch the file only if a test shows otherwise.

**Contract**: `TicketView` inherits `failure_reason` from `TicketStatus`.

#### 4. Tests

**Files**: `tests/test_workflow.py`, `tests/test_api.py`, `tests/test_logs.py`

**Intent**: Prove helpdesk exhaustion and act errors end as `helpdesk_unavailable` failures that are visible in the status, the API and the logs. Prove a restart mid-action performs the action exactly once.

**Contract**:
- `FakeHelpdesk(1.0)` through the real activities. Check that `handle.result()` raises `WorkflowFailureError` whose cause is an `ApplicationError` with `type == "helpdesk_unavailable"`. The queried status has `step == "failed"`, `steps[-2:] == ["acting", "failed"]` and `failure_reason == "helpdesk_unavailable"`. The helpdesk was called 5 times.
- A fake `act` raising a non-retryable `ApplicationError` → the same `helpdesk_unavailable` failure after 1 attempt ("any act failure").
- **Restart test:** a test-only **async** `act` activity (name `"act"`) calls the real `FakeHelpdesk(0.0).perform(req)` and records `(activity.info().attempt, req.idempotency_key)`. On attempt 1 it then sets a "recorded" event and `await`s a gate that is never set. A synchronous block inside `perform` would stall the worker's event loop and stop it shutting down. Wait for the event, stop worker 1 (`max_cached_workflows=0`), and start worker 2 on the same task queue with the same activity and helpdesk instance. Attempt 2+ returns the result without waiting. Assertions:
  - the recorded attempts are `[1, 2]`, so worker 2 really retried the activity;
  - both attempts used the same idempotency key `ticket-T-1:reply`;
  - an independent execution counter is `1`: a `FakeHelpdesk` subclass increments it only when `perform` records a key that was not yet in `performed`, so a dict overwrite can't hide a second execution;
  - the ticket ends `done` with `result.helpdesk_ref == "HD-1"`.
- API: `api_and_worker` takes an optional helpdesk failure rate. With rate `1.0`, `POST /tickets` T-1 and then `GET /tickets/T-1` returns `status == "failed"`, `step == "failed"` and `failure_reason == "helpdesk_unavailable"`.
- Logs: one worker log line with `reason_code == "helpdesk_unavailable"` carries `ticket_id` and `workflow_id`, following the end-to-end pattern in `test_t1_is_traceable_end_to_end_without_ticket_text`.

#### 5. README

**File**: `README.md`

**Intent**: Explain the act retry limit (5 attempts, backoff capped at 10 s), the `helpdesk_unavailable` failure and how it looks in `GET`, and how to demo it (`HELPDESK_FAILURE_RATE=1.0`). Say that a restart mid-action repeats nothing while the worker process keeps its helpdesk memory. Link the existing known limitation about in-memory keys.

**Contract**: extend the reason-codes subsection from Phase 1 with failed tickets. The "Known limitations" entry about idempotency keys stays.

### Success Criteria:

#### Automated Verification:

- New helpdesk-failure, restart, API and log tests pass: `uv run pytest tests/test_workflow.py tests/test_api.py tests/test_logs.py`
- Full suite passes: `uv run pytest`
- Lint passes: `uv run ruff check`
- Format passes: `uv run ruff format --check`

#### Manual Verification:

- `HELPDESK_FAILURE_RATE=1.0 docker compose up --build`, then `POST` T-1's content under a fresh ID `S07-FAIL-1`, which must answer `202` with `"created": true`. About 15 s later, `GET /tickets/S07-FAIL-1` shows `status: failed`, `step: failed` and `failure_reason: helpdesk_unavailable`. The Temporal UI shows 5 `act` attempts and the failure type `helpdesk_unavailable`.
- The worker logs hold one JSON line with `reason_code: helpdesk_unavailable`, `ticket_id` and `workflow_id`, and no ticket text
- Restart with the default `HELPDESK_FAILURE_RATE=0.3`, then `POST` T-1…T-7's content under fresh IDs `S07-T-1`…`S07-T-7`, each answering `202` with `"created": true`. A reused ID returns the old execution (`REJECT_DUPLICATE`) and proves nothing. Every ticket ends `completed`, or `failed` with a `failure_reason`; none is left running except `S07-T-2`, which waits for approval.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Testing Strategy

### Unit Tests:

- Decide activity: both new `ApplicationError`s, with their type, retryability and model-free message (`ActivityEnvironment`).
- (Fallback only) the cause-to-code mapping, with a `TimeoutError` cause.

### Integration Tests:

- Time-skipped workflow tests: unreadable (non-JSON and step overrun), unavailable, decide timeout, helpdesk exhaustion, act non-retryable error, and a restart mid-action.
- API: a failed ticket's `GET` view.
- Logs: the `helpdesk_unavailable` line carries the IDs.
- Existing FR-011 (d) test unchanged.

### Manual Testing Steps:

1. `HELPDESK_FAILURE_RATE=1.0 docker compose up --build`. `POST` T-1's content as `S07-FAIL-1` and require `202` with `"created": true`. Wait ~15 s, then `GET /tickets/S07-FAIL-1`.
2. Open `ticket-S07-FAIL-1` in the Temporal UI; check 5 `act` attempts and the failure type.
3. Restore the default rate. Submit T-1…T-7's content as `S07-T-1`…`S07-T-7`, each requiring `202` with `"created": true`, and check that every ticket ends in a final state or with a reason. Use new IDs for every scenario: a reused ID returns the earlier execution.

## References

- Roadmap slice: `context/foundation/roadmap.md` S-07
- PRD: `context/foundation/prd.md` FR-004, FR-007, FR-008, FR-011
- Restart/test pattern: `tests/test_workflow.py:301`
- Existing FR-011 (d) test: `tests/test_workflow.py:150`
- Lesson: `context/foundation/lessons.md` ("Ticket text hides in derived payloads")

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Model failures escalate

#### Automated

- [x] 1.1 New model-failure workflow and activity tests pass — 3dc654f
- [x] 1.2 Full suite passes — 3dc654f
- [x] 1.3 Lint passes — 3dc654f
- [x] 1.4 Format passes — 3dc654f

#### Manual

- [x] 1.5 Temporal UI shows three decide attempts then the escalation — 3dc654f

### Phase 2: Helpdesk exhaustion fails cleanly

#### Automated

- [x] 2.1 New helpdesk-failure, restart, API and log tests pass — 7d37d7f
- [x] 2.2 Full suite passes — 7d37d7f
- [x] 2.3 Lint passes — 7d37d7f
- [x] 2.4 Format passes — 7d37d7f

#### Manual

- [x] 2.5 Compose with failure rate 1.0 shows the fresh ticket S07-FAIL-1 failed with helpdesk_unavailable — 7d37d7f
- [x] 2.6 Worker log line with reason_code helpdesk_unavailable carries the IDs and no ticket text — 7d37d7f
- [x] 2.7 Default rate: every example ticket ends in a final state with a reason — 7d37d7f

Manual verification completed on 2026-11-08; see [phase-2-manual-verification.md](phase-2-manual-verification.md) for API, log and Temporal UI evidence.
