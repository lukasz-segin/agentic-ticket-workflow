<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Real LLM Provider Behind a Setting

- **Plan**: `context/changes/real-llm-provider/plan.md`
- **Mode**: Deep
- **Date**: 2026-11-08
- **Verdict**: REVISE
- **Findings**: 1 critical, 2 warnings, 1 observation
- **Disposition**: All four findings accepted during `/10x-implement` (2026-11-08); decisions recorded per finding. F1 and F2 are applied in Phase 1, F3 and F4 in Phase 2.

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | WARNING |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | FAIL |

The existing provider seam, settings split, Temporal retry ownership and error-code mapping are appropriate. Targeted corrections are needed for runtime dependencies, malformed provider responses and live verification. The architecture does not need to be replaced.

## Grounding

Grounding: 12/12 existing paths verified; 4 explicitly new files correctly distinguished; 8/8 referenced symbols verified; brief and plan agree on phases, scope and decisions.

- Existing paths: `pyproject.toml`, `uv.lock`, `agent.py`, `activities.py`, `config.py`, `worker.py`, `tests/test_activities.py`, `tests/test_workflow.py`, `tests/test_api.py`, `tests/test_logs.py`, `README.md`, `.env.example`. Source modules are under `src/agentic_ticket_workflow/`.
- New files: `openai_llm.py`, `tests/test_openai_llm.py`, `tests/test_config.py`, `phase-2-manual-verification.md` in the change folder.
- Symbols: `ChatModel.complete`, `ModelUnavailable`, `Settings.from_env`, `TicketActivities.decide`, `decide_error_code`, `DECIDE_RETRY`, `run_with_model`, `TOOL_SCHEMAS`.
- Progress contract passes: exactly one bottom `## Progress` section, matching phase names, all 16 success criteria represented, and execution checkboxes confined to Progress.
- A focused verification sub-agent checked response handling, exception mapping, settings callers, logging and timeout behavior against the code.
- Requirements checked against the PRD, required stack, infrastructure description and the accepted lesson about model-derived ticket text.

## Findings

### F1 — The adapter's HTTPX import is missing from runtime dependencies

- **Severity**: CRITICAL
- **Impact**: LOW — narrow dependency correction
- **Dimension**: Plan Completeness
- **Location**: Phase 1, Dependency and OpenAI-compatible model; `plan.md:83-85`, `plan.md:105`.
- **Detail**: The plan says adding `openai>=3.46.0` brings `httpx` into runtime, while specifying a direct `httpx.Client` import in the adapter. The cached `openai==3.46.0` distribution actually declares `httpx2<3,>=2.12.0`, with no `httpx` dependency. The repository currently declares `httpx` only in the dev group (`pyproject.toml:24-29`). Docker installs with `uv sync --frozen --no-dev` (`Dockerfile:17`, `Dockerfile:22`), so a direct adapter import of `httpx` would fail in the image even though local tests have it. Depending on import placement, this can also prevent the default fake worker from starting. The official SDK reference likewise documents HTTPX2 as the default transport. [OpenAI Python SDK reference](https://developers.openai.com/api/reference/python)
- **Fix**: Explicitly add `httpx` as a runtime dependency with `uv add httpx` alongside `uv add openai`, keeping the planned legacy-client injection and API tests; update the dependency contract and verify the built Docker image starts in fake and real modes. The cached SDK accepts a legacy `httpx.Client`, so that test seam itself does not require a redesign.
- **Decision**: ACCEPTED (adapted, Phase 1). The adapter imports no HTTP library at runtime (`httpx2` only under `TYPE_CHECKING`); tests inject `httpx2.Client(transport=httpx2.MockTransport(...))`, the SDK's own transport. No `httpx` runtime dependency was needed: the built image has no `httpx`, and `build_model` creates `OpenAIChatModel` inside it.

### F2 — Malformed success responses bypass the unreadable-answer path

- **Severity**: WARNING
- **Impact**: MEDIUM — define the adapter's response-validation boundary
- **Dimension**: Blind Spots
- **Location**: Phase 1, OpenAI-compatible model and tests; `plan.md:104-110`, `plan.md:154-164`.
- **Detail**: The adapter contract catches connection/status errors and empty choices, but leaves response decoding and malformed message envelopes unspecified. Offline probes against the exact cached SDK produced `JSONDecodeError` for an HTTP 200 JSON response containing invalid JSON, and `AttributeError` when extracting content from a choice with `message: null`. These happen inside `model.complete`, before the loop's decision/tool validation guards (`agent.py:80`, `agent.py:83-102`). The activity catches only the named agent exceptions (`activities.py:29-47`), and the workflow rethrows unknown failures (`workflow.py:120-123`), so these provider answers fail the workflow instead of escalating with `unreadable_model_answer`. Unexpected response-validation errors may also carry model-derived details into Temporal failure history: its installed failure converter retains `str(exception)` (`.venv/Lib/site-packages/temporalio/converter/_failure_converter.py:108-114`). This is the same class of boundary problem covered by the accepted privacy lesson.
- **Fix**: Validate the response envelope and message/tool-call fields at the adapter boundary, and translate expected JSON-decoding and response-schema failures to a fixed-message `UnreadableModelAnswer from None`. Add HTTP-level cases for invalid JSON, missing/null choices, null messages and malformed tool-call fields, plus an activity/workflow assertion that the sanitized error ultimately escalates with the intended code. Keep unexpected programming errors visible instead of catching every exception indiscriminately.
  - Strength: Reuses the existing unreadable-answer retry/escalation path without changing the workflow or making decision parsing lenient.
  - Tradeoff: Requires explicit envelope checks and several negative-response fixtures.
  - Confidence: HIGH — two escaping failure modes were reproduced with SDK 3.46.0; the downstream error routing was verified in source.
  - Blind spot: The selected live provider may have additional malformed response variants; this is not a promise to normalize every arbitrary server bug.
- **Decision**: ACCEPTED (Phase 1). The adapter calls `with_raw_response.create` and validates the body with small Pydantic models (`choices` non-empty, `message` an object, `content` a string or null, `tool_calls` a list of objects); any `ValidationError`, including invalid JSON, becomes `UnreadableModelAnswer` with a fixed message, `from None`. Tool-call fields are still validated once, in `agent.decide`. Tests: `test_malformed_responses_are_unreadable_answers` (7 cases), `test_malformed_tool_call_is_an_unreadable_answer`, `test_malformed_provider_response_raises_a_retryable_unreadable_answer`, `test_malformed_real_provider_response_escalates_after_the_retry_limit`.

### F3 — The live smoke test can stall on refunds or pass without a usable model

- **Severity**: WARNING
- **Impact**: LOW — make the verification procedure explicit
- **Dimension**: End-State Alignment
- **Location**: Desired End State and Phase 2 manual verification; `plan.md:36`, `plan.md:243-247`, `plan.md:266-271`.
- **Detail**: The test requires all seven tickets to become terminal, but gives no approval/rejection step for valid refunds. T-2 is expected to wait for approval under the PRD, and the workflow uses a real 24-hour timer in compose. The proposed short smoke run therefore has no defined way to finish a normal T-2 outcome. Conversely, the stated acceptance criterion, "each with a decision or a reason code," can pass when every known customer escalates because the provider rejects tools or JSON mode; that does not demonstrate that S-08's real model actually works. The brief already identifies this provider-compatibility risk (`plan-brief.md:65`, `plan-brief.md:72`).
- **Fix**: Specify fresh IDs, a bounded polling period and deterministic Helpdesk settings for the smoke run. Require at least one known-customer ticket to complete a real tool-call/decision/check path, with evidence of a tool round trip. Explicitly inspect and manually approve or reject each valid refund that reaches `awaiting_approval`, including T-2; use a fresh controlled rejection for any unexpected T-6 refund proposal. Record those choices and terminal outcomes. Test a wrong key against a provider that enforces authentication. Preserve T-7's zero-call assertion separately rather than treating absence of a success log as proof of zero requests.
- **Decision**: ACCEPTED (Phase 2). The smoke run uses fresh IDs, `HELPDESK_FAILURE_RATE=0`, a bounded poll, an explicit approve/reject of every refund that reaches `awaiting_approval`, at least one known-customer ticket with a real tool round trip, a wrong key against an auth-enforcing provider, and a T-7 zero-call check.

### F4 — Temporal timeout does not stop the synchronous provider loop

- **Severity**: OBSERVATION
- **Impact**: MEDIUM — decide whether documenting bounded extra work is sufficient
- **Dimension**: Blind Spots
- **Location**: Performance Considerations and Phase 1 worker/activity wiring; `plan.md:29`, `plan.md:275`.
- **Detail**: The plan accepts the 60-second activity timeout but treats the underlying blocking loop as harmless. `activities.py:30` uses `asyncio.to_thread`; canceling the awaiting activity does not terminate that thread. The thread can finish a provider call and start later iterations while a retry runs, or after the workflow has escalated. Each invocation remains capped at six model calls, but the Temporal timeout is not a deadline for the actual HTTP work. Also, the performance paragraph's "up to 4" round trips is not the loop's bound: it allows six (`agent.py:79-105`). No unchecked Helpdesk action can result from this detached model work, but provider usage and shutdown duration can exceed the apparent activity lifetime.
- **Fix**: Document the actual six-call bound and possible work after timeout as an MVP limitation, distinguishing the per-operation client timeout from an overall deadline. If stopping further requests is required, add an attempt-scoped cancellation/deadline check before each provider call, with an offline test proving no next call starts after cancellation.
  - Strength: Makes the tradeoff explicit while preserving the existing workflow and provider seam.
  - Tradeoff: Documentation accepts bounded extra usage; cooperative cancellation requires additional activity-to-adapter state and cannot immediately kill an in-flight synchronous call.
  - Confidence: HIGH — the loop and `to_thread` use are directly visible; the Temporal worker cancels the async task (`.venv/Lib/site-packages/temporalio/worker/_activity.py:744-762`).
  - Blind spot: No timed concurrent-retry experiment was run; the live provider's response and shutdown timings remain unmeasured.
- **Decision**: ACCEPTED as a documented limitation (Phase 2 README). No cooperative cancellation: detached work is bounded by `max_steps` (6) calls of 20 s each, and its output never reaches the helpdesk unchecked. The plan's "up to 4 round trips" is corrected to the loop's bound of 6 in the README.

## Verification performed

Read-only source review and offline SDK probes; no application implementation, dependency installation, live provider requests or full test-suite run was needed for this review.

The SDK was loaded from the existing uv cache into a separate Python process without changing the project's environment or lockfile. Synthetic requests used `httpx.MockTransport`; no credentials or network were used.

```text
SDK 3.46.0
legacy_httpx_client_accepted OpenAI
invalid_json JSONDecodeError
missing_choices caught by empty-choices guard
null_choices caught by empty-choices guard
null_message AttributeError
```

Cached package evidence: `C:/Users/lukas/AppData/Local/uv/cache/archive-v0/rMk8RlyYGPZeulkO/openai-3.46.0.dist-info/METADATA:26` declares `Requires-Dist: httpx2<3,>=2.12.0`. Its `openai/_base_client.py:1031-1038` accepts both legacy HTTPX and HTTPX2 clients; `openai/_response.py:265` decodes the response JSON.

The existing settings callers and non-retryable escalation routing match the plan. Application exception logging retains only error type and stack frames (`logs.py:79-83`); the review found no separate demonstrated logging leak for normally caught SDK errors.

## Next step

Resolve F1-F3 in the plan before implementation; record a decision for F4. Resume finding triage with `/10x-plan-review context/changes/real-llm-provider/reviews/plan-review.md`.
