<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Real LLM Provider Behind a Setting

- **Plan**: `context/changes/real-llm-provider/plan.md`
- **Scope**: Completed phases 1–2 of 2; Progress 16/16 complete
- **Date**: 2026-11-08
- **Verdict**: APPROVED — one minor warning
- **Findings**: 0 critical, 1 warning, 0 observations
- **Git scope**: `36b8611..8f8fc25`; implementation commits `bd2e091` and `bf13a72`, with subsequent plan bookkeeping and editor-ignore housekeeping

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — Nested tool-call fields are echoed without normalization

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence / Safety & Quality
- **Location**: `src/agentic_ticket_workflow/openai_llm.py:70`; response schema at line 28; request-shape coverage in `tests/test_openai_llm.py:22`
- **Detail**: Phase 1 requires each returned tool call to contain only `id`, `type`, and `function: {name, arguments}`. The adapter strips assistant-level extras, but its nested calls remain arbitrary dictionaries and are returned unchanged. `agent.decide` validates required fields, then appends the original assistant message. An offline probe through the installed SDK and `httpx2.MockTransport` confirmed that a response-only call field `index` and a nested `function.provider_extra` appear in the second outgoing request. A synthetic strict endpoint rejecting those fields with HTTP 400 produces `ModelRequestRejected(error_type="BadRequestError")`, which the existing activity maps to a non-retryable `llm_unavailable` escalation. The committed request-shape test asserts exact assistant keys but does not check nested key sets. This is a narrow compatibility gap; no failure with the smoke-tested OpenAI endpoint was established.
- **Fix**: Rebuild nested tool calls using only the planned keys, retaining sanitized unreadable-answer handling for malformed calls. Extend the HTTP-level request-shape test with response-only extras at both levels and assert exact nested key sets in the second request.
- **Decision**: FIXED — `_echoed` in `openai_llm.py` keeps only `id`, `type` and `function: {name, arguments}`; a malformed call is passed on unchanged so `decide` still reports "bad tool call". The T-1 request-shape test adds `index` and `function.provider_extra` and asserts the exact nested key sets (it fails without the fix). 156 tests, lint and format pass.

## Plan and scope assessment

The dependency, exception contracts, provider error classification, activity routing, settings separation, worker selection, offline tests and documentation match the intended behavior, subject to F1. No major drift or missing implementation was found. API independence is covered by settings tests and the recorded Compose check; an unchanged `tests/test_api.py` is not a missing behavior.

The accepted decisions in `reviews/plan-review.md` explain three deliberate differences from the original plan: HTTPX2 instead of legacy HTTPX injection; raw-response Pydantic validation instead of lenient SDK response construction; and documentation of provider work continuing after a Temporal timeout. These are accepted amendments, not new findings. The thread/timeout limitation remains documented and is not reopened here.

Shared test helpers, phase-1 verification evidence and roadmap updates support the planned work. The separate `.vscode/` ignore entry is harmless housekeeping. Business-rule isolation, unchanged workflow commands, fake-mode defaults, refund validation and approval requirements remain intact.

## Automated verification

| Command / check | Result |
|-----------------|--------|
| `uv run pytest tests/test_openai_llm.py tests/test_config.py tests/test_activities.py tests/test_workflow.py tests/test_logs.py` | PASS — 91 tests, 30.94 s |
| `uv run pytest` | PASS — 156 tests, 46.59 s |
| `uv run ruff check` | PASS — All checks passed |
| `uv run ruff format --check` | PASS — 84 files already formatted |
| SDK-import search with `rg` for `import openai` or `from openai` in `src` | PASS — only `openai_llm.py:11` |
| Empty `LLM_API_KEY` check in `.env.example` | PASS — line 15 is `LLM_API_KEY=`; optional trailing CR tolerated on Windows |

Phase 2 repeats the full-suite/lint/format commands from Phase 1; each distinct command was run once against the reviewed final tree. Tests used fake activities and mock provider transports without a real API key or provider request. Some uv commands initially hit a sandbox cache-lock permission error; the lint/format checks and the standalone offline reproduction succeeded with approved escalation. Git used a command-local `safe.directory` override; no global Git configuration was changed.

Independent plan-drift and safety/pattern reviews agreed on F1. The standalone reproduction recorded:

```text
http_requests: 2
echoed_tool_keys: [function, id, index, type]
echoed_function_keys: [arguments, name, provider_extra]
exception: ModelRequestRejected
error_type: BadRequestError
```

## Manual verification evidence

All seven manual Progress items are checked. The committed evidence supports each item; no unsupported completion mark was identified:

- **1.6–1.7**: `phase-1-manual-verification.md` records the fake-mode T-1 reply citing KB-1, the fake-mode startup log, and the missing-model startup failure while the API returns 404. It includes fresh IDs, timestamps and restoration details.
- **2.5–2.6**: `phase-2-manual-verification.md` records OpenAI / `gpt-4.1-mini`, fresh IDs and final outcomes for all seven tickets. T-2's valid 49 EUR refund was explicitly approved; T-6 completed as a reply without a refund.
- **2.7–2.8**: The same record describes the active request-count hook, zero provider requests for T-7, its `unknown_customer` escalation, and ID/sensitive-content checks on worker logs.
- **2.9**: Wrong-key evidence records exactly one outgoing request, a single decide attempt, `AuthenticationError`, non-retryable Temporal failure and final `llm_unavailable` escalation.

These records were inspected during this review. The live scenarios, temporary raw evidence and Temporal UI captures were not independently rerun or revalidated; this review made no live provider requests and changed no running services.

## Triage

F1 fixed during triage (see its Decision). `change.md` is stamped `impl_reviewed`; plan Progress remains unchanged.
