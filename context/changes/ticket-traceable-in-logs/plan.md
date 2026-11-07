# Ticket Traceable in Logs Implementation Plan

## Overview

FR-010 / roadmap S-02: an operator can follow one ticket through every log line from the API, the workflow and the activities by its `ticket_id` and `workflow_id`. Logs are JSON, one object per line, and carry steps and decisions but never ticket text. This also closes the S-01 review carry-over F8: `LOG_LEVEL` is set in compose and `.env.example` but never read.

## Current State Analysis

- There's no structured logging. `worker.py:18` hardcodes `logging.basicConfig(level=logging.INFO)`. The API configures no logging, and its only log line is the 503 warning in `_temporal_unavailable` (`api.py:25-29`), which uses printf-style text.
- The API is started by the Dockerfile CMD `uvicorn agentic_ticket_workflow.api:app ...`, so uvicorn writes plain-text startup lines and access lines (`GET /tickets/T-1 HTTP/1.1 200`). Access lines carry no `workflow_id`.
- The workflow (`workflow.py`) and activities (`activities.py`) log nothing. The seams already exist: `TicketWorkflow._enter(step)` (`workflow.py:84`), the decision assignment (`workflow.py:54`), the refund override (`workflow.py:58-60`), the act result (`workflow.py:63`), and the two activity methods.
- `workflow_id_for(ticket_id)` = `f"ticket-{ticket_id}"` (`workflow.py:28`). The mapping is ours and can be inverted.
- Temporal SDK 1.35.0: `workflow.logger` / `activity.logger` are `LoggerAdapter`s over the `temporalio.workflow` / `temporalio.activity` loggers. They put a `temporal_workflow` / `temporal_activity` dict (with `workflow_id`, `run_id`/`workflow_run_id`, `attempt`, `activity_type`, …) on `extra`. By default they also append that dict to the message text (`workflow_info_on_message` / `activity_info_on_message = True`). The workflow adapter skips logging during replay (`log_during_replay = False`). Per-call `extra` is merged over the Temporal dict. The adapter classes are public as `temporalio.workflow.LoggerAdapter` and `temporalio.activity.LoggerAdapter`.
- The SDK's own activity failure line (`"Completing activity as failed"`, `exc_info=True`, `temporalio/worker/_activity.py`) goes through `temporalio.activity.logger`, so it carries `temporal_activity.workflow_id`. That is the line written on every helpdesk retry.

## Desired End State

- Every log line from the API process and the worker process is one JSON object on stdout: `ts`, `level`, `logger`, `message`, plus `ticket_id` and `workflow_id` whenever the line concerns a ticket, plus only allow-listed fields.
- `grep T-1` (or the README's Log Analytics query) shows the ticket's path: submitted at the API → steps `received`, `deciding`, `acting`, `done` → tools used and the decision (category, priority, action type) → the helpdesk action with its ref → any SDK retry warning with `error_type` and stack frames.
- No line contains the ticket body or subject, model-written text (reply message, reasons, tool arguments), or an exception message.
- `LOG_LEVEL` sets the `agentic_ticket_workflow` logger's level. Every other logger (root, `temporalio.*`, `uvicorn.*`) runs at max(INFO, `LOG_LEVEL`). So `LOG_LEVEL=DEBUG` never switches on the SDK's payload-dumping debug lines. An invalid `LOG_LEVEL` fails at startup.
- `uv run pytest` passes, including the new formatter, level and end-to-end trace tests.

### Key Discoveries:

- At DEBUG the SDK logs `"Completing activity with completion: %s"` (`temporalio/worker/_activity.py`), the full activity result: decision, `tool_calls` with the `search_kb` query, which is subject plus body. That is why other loggers are capped at max(INFO, `LOG_LEVEL`).
- `workflow.logger`/`activity.logger` sit under `temporalio.*`, so under that cap our workflow and activity lines would lose DEBUG. Wrap our own `agentic_ticket_workflow.*` loggers with the SDK's public adapters instead. They stay replay-safe and still get the Temporal extras.
- Lesson "Ticket text hides in derived payloads" (`context/foundation/lessons.md`): reply `message`, escalate/close `reason`, `article_ids`, refund `invoice_id` and tool arguments all come from the model. Only Literal-typed values (category, priority, action type, step) and code-produced values (tool names, `helpdesk_ref`, reason codes the workflow sets itself) are safe.
- `GET /tickets/{ticket_id}` currently accepts any string, so arbitrary user text would reach the log. The `Ticket` model already defines `Identifier` (`models.py:8`).

## What We're NOT Doing

- No OpenTelemetry or tracing (FR-014, parked).
- No generic HTTP access log. The API writes its own line per ticket request, and non-ticket paths (`/docs`, unknown routes) aren't logged.
- No ID fields on SDK-internal lines that carry no Temporal extras (e.g. `temporalio.worker._workflow` "Failed activation on workflow … with ID …"). They are still JSON, and the ID is in their message text.
- No exception messages or chained causes in logs, not even for our own sanitized errors.
- No logging inside `agent.py`, `helpdesk.py` or `tools.py`. The plain-Python core stays free of logging. Activities log around it.
- No reason-code logging for S-03–S-07 escalations or failures. Those slices add their code-produced reasons to the same `reason` field.
- No log shipping or alerts config (README/infra only, S-09).

## Implementation Approach

One small module, `logs.py`, owns the format and the levels. A stdlib `logging.Formatter` subclass builds each line from a fixed set of keys plus an **allow-list** of extra fields, so anything not on the list (a stray `extra`, a model payload) is dropped rather than serialized. IDs are filled in both directions: `workflow_id` is taken from an explicit extra or from Temporal's `temporal_workflow`/`temporal_activity` dict, and `ticket_id` is derived from it through the inverse of `workflow_id_for` (and vice versa). SDK lines get both IDs for free, and call sites don't repeat themselves. Both processes call `configure_logging(settings.log_level)` before anything logs. The API gets a Python entrypoint so uvicorn's own lines go through the same formatter.

## Critical Implementation Details

- **Ordering in the API entrypoint:** `configure_logging` must run before `uvicorn.run(..., log_config=None, access_log=False)`. With `log_config=None` uvicorn leaves logging alone, so its loggers propagate to our root handler. Configuring inside `lifespan` would be too late: the startup lines would already be plain text.
- **Workflow sandbox:** the workflow's adapter is built at module level in `workflow.py` from `logging.getLogger("agentic_ticket_workflow.workflow")` via `workflow.LoggerAdapter(..., None)`, with `workflow_info_on_message = False`. Call it only from workflow code. Don't import `logs.py` into `workflow.py`.
- **`configure_logging` must be idempotent.** It replaces the root handlers, never appends, because tests and repeated calls must not duplicate lines.

## Phase 1: Logging core

### Overview

Add the JSON formatter, the level setup and the `LOG_LEVEL` setting, with unit tests. Nothing calls them yet.

### Changes Required:

#### 1. ID mapping inverse

**File**: `src/agentic_ticket_workflow/workflow.py`

**Intent**: Add the inverse of `workflow_id_for`, so the formatter can derive `ticket_id` from a Temporal workflow ID. Both directions of the mapping live in one place.

**Contract**: `ticket_id_from(workflow_id: str) -> str | None`. It returns the part after the `ticket-` prefix, or `None` when the prefix is absent.

#### 2. JSON formatter and level setup

**File**: `src/agentic_ticket_workflow/logs.py` (new)

**Intent**: Turn every `LogRecord` into one JSON line that is safe by construction, and apply the level rule.

**Contract**:
- `class JsonFormatter(logging.Formatter)`. Output keys:
  - `ts`: ISO-8601 UTC.
  - `level`.
  - `logger`.
  - `message`: `record.getMessage()`.
  - `ticket_id` / `workflow_id` (only when known). `workflow_id` comes from the record's `workflow_id` extra, else `temporal_workflow["workflow_id"]`, else `temporal_activity["workflow_id"]`. `ticket_id` comes from the `ticket_id` extra, else `ticket_id_from(workflow_id)`. A `workflow_id` missing while `ticket_id` is known comes from `workflow_id_for`.
  - From the Temporal dicts: `run_id` (workflow `run_id` or activity `workflow_run_id`), `attempt`, `activity_type`.
  - The allow-listed extras, when present: `step`, `status`, `created`, `category`, `priority`, `action`, `tools`, `reason`, `helpdesk_ref`. The docstring states that `reason` takes only code-produced reason codes, never model text. Every other extra is dropped.
  - With `exc_info`: `error_type` (the exception class name) and `stack` (a list of `"file:line in function"` frames from the traceback), with no exception message and no chained causes. `exc_text`/`stack_info` are never emitted.
  - `json.dumps(..., default=str)`, one line.
- `configure_logging(level: str, stream: TextIO | None = None) -> None`:
  - Replaces root handlers with one `StreamHandler(stream or sys.stdout)` using `JsonFormatter`.
  - Root level = max(INFO, `level`).
  - The `agentic_ticket_workflow` logger level = `level`.
  - Resets the `uvicorn`, `uvicorn.error`, `uvicorn.access` and `temporalio` loggers to no handlers, NOTSET and propagate, so they follow the root.

#### 3. LOG_LEVEL setting

**File**: `src/agentic_ticket_workflow/config.py`

**Intent**: Read `LOG_LEVEL` (closes F8), validated like the other settings.

**Contract**: `Settings.log_level: str`, from `LOG_LEVEL` (default `INFO`), upper-cased. It must be one of `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`, otherwise `ValueError`.

#### 4. Unit tests

**File**: `tests/test_logs.py` (new)

**Intent**: Pin the format and the safety guard, and the level rule.

**Contract**: tests for:
- (a) One parseable JSON object per line with the fixed keys.
- (b) A record carrying only `temporal_activity={"workflow_id": "ticket-T-1", "attempt": 2, ...}` gets `ticket_id == "T-1"`, `workflow_id == "ticket-T-1"` and `attempt == 2`.
- (c) A non-allow-listed extra (e.g. `body=...`) is absent from the output.
- (d) A record with `exc_info` for `ValueError("secret ticket text")` has `error_type == "ValueError"`, a non-empty `stack`, and `"secret ticket text"` nowhere in the line, including when it is the `__cause__` of another exception.
- (e) `configure_logging("DEBUG")`: the `agentic_ticket_workflow` effective level is DEBUG, while `temporalio` and `uvicorn.access` are INFO.
- (f) `configure_logging("WARNING")`: all of them are WARNING.
- (g) `Settings.from_env()` with `LOG_LEVEL=verbose` raises `ValueError`, and `LOG_LEVEL=debug` is accepted as `DEBUG`.

A fixture restores the root handlers and logger levels after each test.

### Success Criteria:

#### Automated Verification:

- Logging unit tests pass: `uv run pytest tests/test_logs.py`
- Full suite still passes: `uv run pytest`

#### Manual Verification:

- Reading `logs.py` confirms the allow-list is the only way an extra reaches the output

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Wire entry points and emit ticket lines

### Overview

Both processes use the formatter, and the API, workflow and activities emit the ticket's path. An end-to-end test proves the trace and the no-text rule.

### Changes Required:

#### 1. Worker entrypoint

**File**: `src/agentic_ticket_workflow/worker.py`

**Intent**: Replace `basicConfig(INFO)` with `configure_logging(settings.log_level)`, called after `Settings.from_env()` and before connecting. The startup line becomes structured.

**Contract**: The startup line is a fixed message with the task queue as text. Not a ticket line.

#### 2. API entrypoint and request lines

**Files**: `src/agentic_ticket_workflow/api.py`, `Dockerfile`

**Intent**: Start the API from Python, so logging is configured before uvicorn starts. Write one line per ticket request in place of the access log. Reject malformed ticket IDs in the path, so arbitrary user text never reaches a log line.

**Contract**:
- `serve()` + `if __name__ == "__main__": serve()`. It reads `Settings.from_env()`, calls `configure_logging(settings.log_level)`, then `uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None, access_log=False)`. The Dockerfile CMD becomes `["python", "-m", "agentic_ticket_workflow.api"]`, and compose's `api` service keeps inheriting it.
- `GET /tickets/{ticket_id}`: `ticket_id` uses the same pattern as `models.Identifier`, via `fastapi.Path`. A malformed ID gets 422 instead of 404. `/tickets/NOPE` is still 404.
- Lines, all with `ticket_id` and `workflow_id` extras:
  - INFO `"ticket submitted"` `created=True`, or INFO `"ticket already submitted"` `created=False`.
  - INFO `"ticket not found"`.
  - WARNING `"temporal unavailable"` with `error_type` as an allow-listed extra. Rewrite `_temporal_unavailable` from printf text to structured fields.
  - DEBUG `"ticket status read"` with `status` and `step`.

#### 3. Workflow lines

**File**: `src/agentic_ticket_workflow/workflow.py`

**Intent**: Log the steps and the decision, replay-safe, under our own logger. IDs come from the Temporal extras through the formatter.

**Contract**:
- Module-level `log = workflow.LoggerAdapter(logging.getLogger("agentic_ticket_workflow.workflow"), None)`, with `workflow_info_on_message = False`.
- INFO `"step entered"` `step=<step>`, for `received` and in `_enter`.
- INFO `"decision made"` with `category`, `priority`, `action` (type only) and `tools` (names only).
- INFO `"refund held for approval"` with `action="escalate"` and `reason="refund_needs_approval"`.
- INFO `"action performed"` with `action` (type) and `helpdesk_ref`.

#### 4. Activity lines

**File**: `src/agentic_ticket_workflow/activities.py`

**Intent**: Log the outside calls, with the attempt number from the Temporal extras. Retry failures are already logged by the SDK's `"Completing activity as failed"` line, which the formatter turns into `error_type` + `stack` + both IDs, so no extra code is needed for them.

**Contract**:
- Module-level `log = activity.LoggerAdapter(logging.getLogger("agentic_ticket_workflow.activities"), None)`, with `activity_info_on_message = False`.
- `decide`: INFO `"model decided"` `tools=[names]`.
- `act`: INFO `"helpdesk action done"` with `action` (type) and `helpdesk_ref`.

#### 5. End-to-end trace test

**File**: `tests/test_logs.py`, or alongside the API test in `tests/test_api.py` (follow its setup)

**Intent**: Prove FR-010 the way the operator sees it, under the most dangerous level.

**Contract**:
- Call `configure_logging("DEBUG", stream=<buffer>)`.
- Run T-1 through the HTTP API with the real activities, `FakeChatModel` and a `FakeHelpdesk` that fails its first call and then succeeds (a stub `rng`). Then parse every buffered line.
- Assert:
  - Every line is JSON.
  - Every line that has a `ticket_id` or `workflow_id` has both, and they are `T-1` / `ticket-T-1`.
  - The step lines cover `received`, `deciding`, `acting` and `done`.
  - A `"decision made"` line has `category="account"`, `priority="normal"` and `action="reply"`.
  - A `"ticket submitted"` line exists.
  - A WARNING line has `error_type="HelpdeskTemporaryError"` and both IDs.
  - Neither T-1's `body` nor its `subject`, nor the reply `message`, occurs in any line.
- Restore the logging state afterwards.

#### 6. README note

**File**: `README.md`

**Intent**: Give the reviewer a short "Logs" note: one example line, the fields, the `LOG_LEVEL` rule (our logger only, others at least INFO, and why), and that ticket text is never logged. The existing Log Analytics query stays.

**Contract**: A new short subsection near the existing logs text (around `README.md:86`).

### Success Criteria:

#### Automated Verification:

- Full suite passes, including the end-to-end trace test: `uv run pytest`
- Image builds with the new API entrypoint: `docker compose build`

#### Manual Verification:

- `docker compose up`, then `POST /tickets` with T-1. `docker compose logs api worker` shows only JSON lines, and `docker compose logs | grep T-1` shows the submit, all four steps, the decision and the helpdesk action, with no ticket text.
- With `HELPDESK_FAILURE_RATE=0.3`, a retried ticket shows a WARNING line with `error_type` and both IDs.
- `LOG_LEVEL=DEBUG docker compose up`: our DEBUG lines (status read) appear, and no `temporalio` DEBUG lines do.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Testing Strategy

### Unit Tests:

- Formatter: fixed keys, Temporal-extra ID derivation, allow-list drop, exception type + frames without the message (including a chained cause).
- Levels: DEBUG/WARNING rule across our logger, `temporalio` and `uvicorn`, plus `LOG_LEVEL` validation.

### Integration Tests:

- T-1 end to end through the API with one helpdesk retry, under `configure_logging("DEBUG")`: the trace is complete, both IDs are on every ticket line, and no ticket or model text appears anywhere.

### Manual Testing Steps:

1. `docker compose up --build`. Submit T-1 and check `docker compose logs` for JSON-only output and the full trace.
2. Submit T-1 again and check for a `"ticket already submitted"` line.
3. `GET /tickets/NOPE` returns 404 and writes a `"ticket not found"` line. `GET /tickets/has%20space` returns 422 and writes no ticket line.

## Performance Considerations

None. Each ticket writes about ten lines.

## Migration Notes

The Dockerfile CMD changes from the `uvicorn` CLI to `python -m agentic_ticket_workflow.api`, with the same host and port. The described Azure deployment uses the same image, so no infra doc change is needed.

## References

- PRD FR-010: `context/foundation/prd.md:133`
- Roadmap S-02: `context/foundation/roadmap.md` (risk notes: replay-safe logging, F8, the lesson)
- S-01 review F5/F8: `context/archive/2026-11-06-first-ticket-answered/reviews/impl-review.md`
- Lesson: `context/foundation/lessons.md` — "Ticket text hides in derived payloads"
- Temporal SDK adapters: `.venv/Lib/site-packages/temporalio/workflow/_sandbox.py` (`LoggerAdapter`), `temporalio/activity.py` (`LoggerAdapter`, `_logger_details`)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Logging core

#### Automated

- [x] 1.1 Logging unit tests pass: `uv run pytest tests/test_logs.py`
- [x] 1.2 Full suite still passes: `uv run pytest`

#### Manual

- [x] 1.3 Reading `logs.py` confirms the allow-list is the only way an extra reaches the output

### Phase 2: Wire entry points and emit ticket lines

#### Automated

- [ ] 2.1 Full suite passes, including the end-to-end trace test: `uv run pytest`
- [ ] 2.2 Image builds with the new API entrypoint: `docker compose build`

#### Manual

- [ ] 2.3 `docker compose up` + T-1: JSON-only logs, full trace by `grep T-1`, no ticket text
- [ ] 2.4 Retried ticket shows a WARNING line with `error_type` and both IDs
- [ ] 2.5 `LOG_LEVEL=DEBUG`: our DEBUG lines appear, no `temporalio` DEBUG lines
