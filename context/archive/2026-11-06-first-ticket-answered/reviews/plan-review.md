<!-- PLAN-REVIEW-REPORT -->
# Plan Review: First Ticket Answered End-to-End (S-01) Implementation Plan

- **Plan**: `context/changes/first-ticket-answered/plan.md`
- **Mode**: Deep
- **Date**: 2026-11-06
- **Verdict**: REVISE → SOUND after triage
- **Findings**: 0 critical, 2 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | PASS |
| Plan Completeness | WARNING |

## Grounding
Grounding: 6/6 paths ✓, 3/3 symbols ✓, brief↔plan ✓

## Findings

### F1 — Unbounded query hang and 503 on completed workflow when worker is down

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Architectural Fitness
- **Location**: Phase 3 — HTTP API (`src/agentic_ticket_workflow/api.py`)
- **Detail**: In Phase 3, `GET /tickets/{ticket_id}` calls `handle.query(TicketWorkflow.status)` unconditionally and maps query failures to 503. In Temporal, when a workflow execution is `COMPLETED`, `await handle.result()` already holds the final `TicketStatus` directly in execution history without querying. Querying requires a live worker to poll and evaluate the query task; if the worker process is restarting or offline, `handle.query()` blocks until timeout (up to 60s) before failing with 503. Furthermore, for in-flight workflows, querying without an explicit timeout risks hanging the HTTP response.
- **Fix A ⭐ Recommended**: Check `describe().status`: if `COMPLETED`, return `await handle.result()`; if `RUNNING`, query with a short timeout (e.g. 2–3s) and map query failure/timeout to 503.
  - Strength: Completed tickets remain readable even if worker is down; prevents 60s HTTP client hangs.
  - Tradeoff: Slight branching in `get_ticket` handler.
  - Confidence: HIGH — verified empirically with Temporal Python SDK 1.35.0.
  - Blind spot: None.
- **Fix B**: Query with an explicit short timeout (e.g. 2s) across all statuses.
  - Strength: Single code path for fetching status.
  - Tradeoff: Completed tickets return 503 whenever the worker process is restarting or temporarily absent.
  - Confidence: MEDIUM — simple code, but introduces unnecessary service coupling.
  - Blind spot: Assumes worker is always available to evaluate queries.
- **Decision**: FIXED — Fix A, plus: FAILED workflows go through the timed query path (result() raises for them), and the API test now does a GET after the worker has exited.

### F2 — Missing HTTP response models for submit and status endpoints

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 (`models.py`) & Phase 3 (`api.py`)
- **Detail**: Phase 1 defines `TicketStatus` with `(ticket_id, workflow_id, step, steps, tool_calls, decision, result)`, omitting a `status: str` field (`"running"`, `"completed"`, `"failed"`). Phase 3 states that `GET /tickets/{id}` returns "`TicketStatus` fields plus `status` = lowercased `describe().status.name`". Additionally, `POST /tickets` returns `{ticket_id, workflow_id, created: bool}`, but no `TicketSubmitResponse` model is declared in `models.py`. Without explicit Pydantic response models, FastAPI response validation and serialization are undefined.
- **Fix**: Add `status: str = "running"` to `TicketStatus` (or define `TicketDetailResponse(TicketStatus)` with `status: str`) and define `TicketSubmitResponse(ticket_id: str, workflow_id: str, created: bool)` in `models.py`.
- **Decision**: FIXED — fixed differently: `SubmitResponse` and `TicketView(TicketStatus)` + `status` live in api.py as response_model. TicketStatus is unchanged, because the workflow can't know its own Temporal status.

### F3 — Assistant message tool history and tool correlation in fake LLM

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 — Agent tool loop (`agent.py`) and Fake LLM (`fake_llm.py`)
- **Detail**: Phase 1 specifies appending tool messages `{"role": "tool", "tool_call_id", "content": json}` but does not explicitly specify appending the assistant message with its `tool_calls` array first. In OpenAI chat format, tool messages must follow an assistant message with matching `tool_call_id`s. In addition, standard tool messages omit the tool name, so `FakeChatModel` needs a clean correlation mechanism (such as deterministic IDs like `call_get_customer`, `call_search_kb` or inspecting assistant history) to know which tool results have arrived.
- **Fix**: Explicitly note in Phase 1 that the assistant message is appended to `messages` before tool responses, and adopt deterministic IDs (`call_get_customer`, `call_search_kb`) in `FakeChatModel`.
- **Decision**: FIXED — the assistant reply is appended before its tool results, and the fake model finds the tools already called from `function.name` in assistant tool_calls. Severity upgraded from OBSERVATION to WARNING: without the fix, S-08 breaks on its first real-provider call.
