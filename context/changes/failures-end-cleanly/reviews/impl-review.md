<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Failures End Cleanly

- **Plan**: context/changes/failures-end-cleanly/plan.md
- **Scope**: Full plan, phases 1 and 2 of 2; 12/12 Progress items complete
- **Date**: 2026-11-08
- **Reviewed revision**: 2ec33b52e3bdb34641010896a36894d8f8238ad3
- **Diff**: efd93d4..2ec33b5; implementation commits 3dc654f and 7d37d7f, followed by progress bookkeeping
- **Verdict**: APPROVED
- **Findings**: 0 critical, 0 warnings, 0 observations

## Verdicts

| Dimension | Verdict |
| --- | --- |
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

No substantive findings. No triage is required.

## Plan and implementation evidence

Two independent review passes covered plan drift and safety, quality and existing patterns. Both found no substantive issues.

- `agent.py:14` declares the provider-independent `ModelUnavailable` contract. `activities.py:39` maps unreadable and unavailable model failures to retryable, coded `ApplicationError`s with fixed messages and suppressed exception context. Logs follow the accepted lesson about model-derived ticket text.
- `workflow.py:78` classifies the last decide attempt's cause. Declared failures escalate after retries; a Temporal timeout maps to `llm_unavailable`; unexpected decide errors continue to fail. The timeout unit-test fallback is explicitly allowed by the plan, explained at `tests/test_workflow.py:503`, and recorded in commit 3dc654f's message.
- `models.py:17` adds the failed step; `models.py:123` adds the failure reason. `workflow.py:194` sets the reason, enters the failed step, emits a replay-safe warning and raises a typed non-retryable workflow failure in the required order. There is no escalation fallback through a failing helpdesk.
- The unchanged API inherits the field and queries failed workflows. `tests/test_api.py:94` verifies the resulting HTTP status view.
- `tests/test_workflow.py:553` verifies five helpdesk calls, at most one execution, failed status and the retained decision. `tests/test_workflow.py:576` covers a non-retryable act error after one attempt. `tests/test_logs.py:205` verifies a single warning with both IDs and no ticket subject or body.
- `tests/test_workflow.py:592` interrupts an async act after recording the action, shuts down worker 1 with its cache disabled and finishes through worker 2. Assertions require attempts `[1, 2]`, the same idempotency key, one execution and the original result. `tests/fakes.py:18` counts every write, including an overwrite of an existing key, so unique-key counting cannot hide a duplicate execution. This strengthens the plan's intended independent counter.
- README documents the limits, reason codes, failure view, demo and unconfirmed-action ambiguity. The process-restart limitation is explicit. Changes to roadmap status and change/verification documents are justified bookkeeping; no feature scope expansion was found.

## Automated verification

Commands were rerun during this review against the reviewed revision. All exited successfully.

| Command | Result |
| --- | --- |
| `uv run pytest tests/test_workflow.py tests/test_agent.py` | 61 passed in 24.81 s |
| `uv run pytest tests/test_workflow.py tests/test_api.py tests/test_logs.py` | 65 passed in 48.55 s |
| `uv run pytest` | 121 passed in 48.17 s |
| `uv run ruff check` | All checks passed |
| `uv run ruff format --check` | 74 files already formatted |
| `git diff --check efd93d4..HEAD` | Passed |

## Manual verification evidence

All manual Progress items are checked and have observable evidence.

- **1.5:** Inspected the existing `not-json`, `step-limit` and `unavailable` histories in `%TEMP%/atw-s07-p1-history-check/`. Each schedules `decide`, reaches attempt 3 with `RETRY_STATE_MAXIMUM_ATTEMPTS_REACHED`, then schedules `act` and completes. Failure types are `unreadable_model_answer`, `unreadable_model_answer` and `llm_unavailable`, respectively. The associated verification driver checks the escalation action decoded from the act input. The plan permits reading test history for this criterion.
- **2.5:** [Phase 2 verification record](../phase-2-manual-verification.md) preserves the fresh 202 submission and the failed HTTP view after 17.3 s. Rechecked the saved history: act reaches attempt 5, exhausts retries, and the final workflow error is `helpdesk_unavailable`. Saved UI text for events 18 and 23 displays the attempt and failure type.
- **2.6:** Rechecked the saved failure worker log: exactly one record has `reason_code: helpdesk_unavailable`. The verification record includes its WARNING level and both IDs, and records the raw and decoded log checks for sample ticket bodies.
- **2.7:** Rechecked saved example status responses: six completed at `done`; only S07-T-2 is running at `awaiting_approval`. The verification record confirms all seven submissions returned 202 with `created: true` and the rate was restored to 0.3.

These checks use evidence from the preceding manual verification; this review did not resubmit IDs or recreate the Compose stack. Raw artifacts remain temporary local evidence. This report and the Phase 2 record preserve the conclusions.

## Accepted limits

The restart test retains one fake-helpdesk instance in one process. It proves idempotency while that memory survives; a real process restart can repeat an interrupted action. Persistent idempotency, production workflow versioning and real provider integration remain outside the approved scope. Hung decide activity behavior is checked through the permitted error-mapping fallback rather than a slow workflow-level timeout test. Unexpected decide/check bugs may still fail without a reason code, as accepted in the plan.

Only this report and the `impl_reviewed` change status were written by the review. Application code and Progress were left unchanged.
