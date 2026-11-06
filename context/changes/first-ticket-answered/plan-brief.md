# First Ticket Answered End-to-End (S-01) — Plan Brief

> Full plan: `context/changes/first-ticket-answered/plan.md`

## What & Why

Build the thinnest complete chain that answers ticket T-1 in fake-LLM mode, with no API key:

HTTP intake → Temporal workflow → LLM tool loop (`get_customer` / `get_invoices` / `search_kb`) → idempotent fake helpdesk → readable status.

This is roadmap slice S-01, the north star. Every later slice reuses this chain, so it goes first.

## Starting Point

- `Dockerfile`, `docker-compose.yml` and `.env.example` already exist and point at `agentic_ticket_workflow.api:app` and `agentic_ticket_workflow.worker`, but neither module exists.
- `src/` holds only a hello-world `main()`.
- There is no temporalio, no tests and no in-repo sample data.

## Desired End State

- **Run:** `docker compose up` starts everything with no key.
- **Submit:** POST T-1 returns 202 at once. A resubmit returns 200 `created:false`, whether the ticket is running, completed or failed.
- **Status:** GET shows the Temporal status, the current step, the step history, the model's tool calls, the decision (`account` / `normal` / `reply` citing KB-1) and the helpdesk result.
- **Exactly once:** the reply is recorded once even at the default 30 % helpdesk failure rate.
- **Tests:** `uv run pytest` runs the unit, time-skipped workflow and API tests offline after the first run.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Fake model shape | Fixed tool order + ordered keyword-rule table, OpenAI tool-call message shape; no match → escalate | Honestly "simple and rule-based" (FR-009), and S-03/S-04 only append rules |
| Refund before S-05 | Workflow turns any refund into `escalate` (`refund_needs_approval`) | No slice order can ever issue an unapproved refund |
| Status contract | `status` + `step` + `steps` + `tool_calls` + `decision` + `result` | US-01 asks to show "each step", and the tool loop can be seen without the Temporal UI |
| Duplicate POST | 202 new / 200 existing, `{ticket_id, workflow_id, created}` | The caller can tell "started" from "already there"; a changed body is ignored, as the PRD accepted |
| Duplicate detection | `REJECT_DUPLICATE` + catch `WorkflowAlreadyStartedError` | Verified to cover closed workflows too, unlike `USE_EXISTING`, which hides "created" |
| Test server offline | SDK cache + README note on the first-run download | Zero code; verified that it caches `temporal-test-server-sdk-python-1.35.0.exe` |
| Namespace retention | Documented limitation (value confirmed in Phase 3) | No extra compose service; the helpdesk keys still dedupe while the worker runs |
| Retry limits | decide: 3 attempts; act: 5 attempts, 1 s → max 10 s backoff | 5 attempts at 30 % ≈ 0.2 % exhaustion (PRD FR-007) |
| Idempotency key | `ticket-<id>:<action type>` | Deterministic per ticket, so a retried `act` meets the recorded result |

## Scope

**In scope:**
- Packaged sample data, settings and domain models
- The lookup tools, the agent loop with a step limit, the fake model (T-1 rule + fallback) and the fake helpdesk (failures before and after recording)
- `TicketWorkflow` + activities + worker
- `POST /tickets` and `GET /tickets/{id}`
- Unit, workflow and API tests; short README run/test/limitation notes

**Out of scope:**
- Rule checks (S-04) and the approval endpoint/wait/timeout (S-05/S-06)
- Failure-reason mapping (S-07) and `unknown_customer` (S-03)
- JSON logging (S-02) and a real LLM (S-08)
- Retention changes, a test-server prefetch, CI

## Architecture / Approach

The build goes inside out:
- **Plain-Python core** (`models`, `tools`, `agent`, `fake_llm`, `helpdesk`, `config`): no Temporal or FastAPI imports, fully unit-tested.
- **Temporal layer:** `TicketActivities` (`decide`, `act`) wraps the core with injected dependencies. `TicketWorkflow` owns the steps, the status query, the refund guard, the retry policies and the idempotency key.
- **HTTP layer:** `api.py` translates HTTP to the Temporal client, reading the client from `app.state` so tests can inject `WorkflowEnvironment.client`.
- **Data converter:** everything uses `pydantic_data_converter`.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Plain-Python core + test harness | Data, models, tools, agent loop, fake model, fake helpdesk, unit tests, `uv run pytest` recorded | KB keyword scoring ranks a wrong article first |
| 2. Workflow, activities, worker | `TicketWorkflow` with status query, refund guard, bounded retries; time-skipped answered-ticket test | Sandbox import issues (passed-through models) |
| 3. API + compose smoke + README notes | POST/GET with 202/200/404/503, API test via real activities, `docker compose up` T-1 run | Packaged JSON missing from the non-editable wheel in Docker |

**Prerequisites:** none. Docker is needed only for the Phase 3 manual run; network access is needed once to lock the dependencies and fetch the test server.

**Estimated effort:** ~2–3 h across 3 phases.

## Open Risks & Assumptions

- **Namespace retention:** the dev server's retention value is unconfirmed (believed to be ~24 h). Phase 3 confirms and documents it.
- **Data files in the wheel:** uv_build is assumed to include `data/*.json` in the wheel. The Phase 3 Docker run proves it.
- **Unhandled retry exhaustion:** until S-07, an exhausted `act` or `decide` fails the workflow without a reason code (GET shows `status: failed`).

## Success Criteria (Summary)

- A reviewer runs `docker compose up`, submits T-1, gets its ID at once, and reads a completed status with the KB-1 reply.
- A resubmitted T-1 never processes again, and the reply is recorded once despite helpdesk failures.
- `uv run pytest` passes with no key and no network (after the one-time test-server download).
