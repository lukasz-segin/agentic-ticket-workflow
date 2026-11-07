# Ticket Traceable in Logs — Plan Brief

> Full plan: `context/changes/ticket-traceable-in-logs/plan.md`

## What & Why

FR-010 / roadmap S-02: an operator can follow one ticket through every log line from the API, the workflow and the activities by `ticket_id` and `workflow_id`. The lines are JSON, one per line, and carry steps and decisions but never ticket text. It also closes S-01 review carry-over F8: `LOG_LEVEL` is never read.

## Starting Point

There's no structured logging. The worker hardcodes `basicConfig(INFO)`, the API configures nothing, and uvicorn writes plain-text access lines with no workflow ID. The workflow and activities log nothing. Temporal's SDK already attaches `workflow_id`/`attempt` to its logger extras, and `workflow_id` is `ticket-<ticket_id>`, so it can be inverted.

## Desired End State

Every line from both processes is one JSON object. `grep T-1` shows the submit, the steps `received → deciding → acting → done`, the tools used, the decision (category, priority, action type), the helpdesk action and any retry warning, each with both IDs. No line carries the body, the subject, model-written text or exception messages. `LOG_LEVEL=DEBUG` is safe to turn on.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Uvicorn output | `python -m agentic_ticket_workflow.api` entrypoint, `log_config=None`, no access log; the API logs its own ticket request lines | Every line in the stream is JSON and every ticket line carries both IDs. |
| Errors in logs | `error_type` + stack frames, no message or chained cause | Debuggable, and safe even when a third-party exception embeds model or ticket text. |
| Levels | `LOG_LEVEL` sets only the `agentic_ticket_workflow` logger; every other logger runs at max(INFO, `LOG_LEVEL`) | The SDK's DEBUG lines dump activity payloads (ticket text). |
| Workflow/activity loggers | SDK's public `LoggerAdapter`s around our own `agentic_ticket_workflow.*` loggers | Replay-safe, and they get the Temporal ID extras without falling under the `temporalio` cap. |
| JSON formatting | stdlib `logging.Formatter` subclass with an allow-list of extra fields | No new dependency; unknown extras are dropped, not dumped. |
| ID filling | Formatter derives `ticket_id` ↔ `workflow_id` (from explicit extras or Temporal's dicts) | SDK retry lines get both IDs too, and call sites don't repeat them. |
| Malformed path IDs | `GET /tickets/{id}` validates the `Identifier` pattern (422) | Arbitrary user text never reaches a log line; `/tickets/NOPE` is still 404. |
| Tests | Formatter unit tests + level tests + an end-to-end T-1 trace under DEBUG with one helpdesk retry | Pins the guard and proves FR-010 the way the operator sees it. |

## Scope

**In scope:** `logs.py` (formatter + `configure_logging`), `Settings.log_level`, the worker and API entrypoints, the Dockerfile CMD, log lines at the API, workflow and activity seams, tests, and a short README "Logs" note.

**Out of scope:** OpenTelemetry/tracing (FR-014), a generic access log, IDs on SDK-internal lines with no Temporal extras, logging inside the plain core (`agent`/`helpdesk`/`tools`), reason codes for S-03–S-07, and alerts.

## Architecture / Approach

API, workflow and activities → stdlib loggers under `agentic_ticket_workflow.*` (workflow and activity ones via the SDK adapters) plus third-party loggers → one root handler with `JsonFormatter` → stdout. The formatter's allow-list is the only way an extra reaches the output.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Logging core | Formatter, level rule, `LOG_LEVEL` setting, unit tests | Allow-list too narrow or too wide |
| 2. Wire and emit | Entry points, ticket lines across the layers, end-to-end trace test, README note | Uvicorn/SDK lines escaping the formatter; workflow logging in the sandbox |

**Prerequisites:** S-01 done (it is).
**Estimated effort:** ~1 session, 2 phases.

## Open Risks & Assumptions

- SDK-internal lines without Temporal extras (e.g. "Failed activation …") have IDs only in their message text.
- Malformed `GET /tickets/{id}` now returns 422 instead of 404, a small public-surface change.
- `reason` is logged only for code-produced codes. Later slices must not put model text into it.

## Success Criteria (Summary)

- `grep <ticket_id>` across the API and worker logs gives the ticket's whole path, every line in JSON with both IDs.
- No ticket or model text in any line, even with `LOG_LEVEL=DEBUG` and a helpdesk retry.
- `uv run pytest` passes with no network.
