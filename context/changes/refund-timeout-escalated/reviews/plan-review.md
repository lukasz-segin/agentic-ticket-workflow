<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Refund Timeout Escalated

- **Plan**: `context/changes/refund-timeout-escalated/plan.md`
- **Mode**: Deep
- **Date**: 2026-11-07
- **Verdict**: REVISE
- **Findings**: 1 critical, 2 warnings, 0 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | FAIL |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding

Grounding: 5/5 paths verified, 8/8 symbols verified, brief and plan consistent.

Verified paths: `src/agentic_ticket_workflow/models.py`, `src/agentic_ticket_workflow/workflow.py`, `tests/test_workflow.py`, `tests/test_api.py`, and `README.md`.

Verified symbols: `TicketStatus`, `workflow.wait_condition`, `workflow.now`, `_refuse_unless_awaiting_approval`, `approve_ticket`, `api_and_worker`, `fake_activities`, and `started`.

The review checked the PRD, required stack, infrastructure, bootstrap verification, lessons, current implementation, tests, and local Temporal SDK. A focused sub-agent verified risky claims and swept callers. No omitted consumers requiring changes or new architectural patterns were found. Findings about SDK and test-server scheduling follow source inspection; no runtime race or gated-timer probe was executed. No implementation changes or test-suite runs were performed during the review.

## Findings

### F1 — A late approval can still trigger a refund

- **Severity**: CRITICAL
- **Impact**: MEDIUM — a deadline boundary decision and regression test are needed.
- **Dimension**: End-State Alignment
- **Location**: Implementation Approach and Critical Implementation Details (`plan.md:41`, `plan.md:45`); Phase 1 workflow contract (`plan.md:72`).
- **Detail**: The existing shared approval guard (`src/agentic_ticket_workflow/workflow.py:179`) checks only the current step and whether an answer was already recorded. After worker downtime, an overdue timer and a queued approval can share one activation. The SDK groups Updates before timer jobs (`.venv/Lib/site-packages/temporalio/worker/_workflow_instance.py:481`), so the proposed rule that an accepted approval always wins can issue a refund after the deadline. The planned late-approval tests submit the Update only after the workflow reaches `acting`, missing this scenario. See the [Temporal Python SDK implementation](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/worker/_workflow_instance.py).
- **Fix**: Extend `_refuse_unless_awaiting_approval` to reject when deterministic `workflow.now() >= approval_deadline`, explicitly defining equality as expired. Add a regression test for an overdue approval queued during worker downtime or sharing an activation with the overdue timer. Retain the post-wait check of the recorded approval so an approval accepted before expiry is honoured. Update the brief and README contract to reflect this boundary.
  - Strength: Directly protects FR-006 without changing the API error mapping.
  - Tradeoff: Requires an additional guard and a regression test that controls worker downtime or activation timing; approval eligibility is decided when the workflow processes the Update.
  - Confidence: HIGH — the guard and SDK scheduling establish the missing deadline check.
  - Blind spot: The precise integration-test orchestration has not been exercised.
- **Decision**: ACCEPTED — applied to plan.md (Critical Implementation Details: validator refuses when `workflow.now() >= approval_deadline`, equality = expired; after-wait branch on the recorded approval kept; Phase 1 contract for `_refuse_unless_awaiting_approval`; new test `test_approval_queued_during_worker_downtime_after_the_deadline_is_refused`, which must fail without the check), plan-brief.md (Key Decisions, Architecture, Risks) and the Phase 2 README contract.

### F2 — The gated late-approval test can accidentally trigger retries

- **Severity**: WARNING
- **Impact**: LOW — adjust the test's time advancement.
- **Dimension**: Blind Spots
- **Location**: Phase 1 workflow tests, `test_late_approval_is_refused_and_never_refunds` (`plan.md:85`).
- **Detail**: `env.sleep(timedelta(hours=24, minutes=1))` includes a minute after the gated `act` activity starts at expiry. The activity has a 30-second start-to-close timeout (`src/agentic_ticket_workflow/workflow.py:153`), and `fake_activities` records each invocation before waiting on its gate (`tests/test_workflow.py:58`). The Java test server locks time skipping while an activity is running, so the remaining minute can elapse in real time and cause timeout/retry, defeating the assertion of exactly one act call. Python `env.sleep` delegates to `unlock_time_skipping_with_sleep` (`.venv/Lib/site-packages/temporalio/testing/_workflow.py:768`). See the [activity time lock](https://github.com/temporalio/sdk-java/blob/master/temporal-test-server/src/main/java/io/temporal/internal/testservice/TestWorkflowMutableStateImpl.java#L1016), [test-service sleep](https://github.com/temporalio/sdk-java/blob/master/temporal-test-server/src/main/java/io/temporal/internal/testservice/TestService.java#L104), and [clock advancement](https://github.com/temporalio/sdk-java/blob/master/temporal-test-server/src/main/java/io/temporal/internal/testservice/SelfAdvancingTimerImpl.java#L249).
- **Fix**: Advance by the remaining duration to the recorded approval deadline, wait for `acting`, check both approval refusals, and release the activity gate promptly. Avoid advancing an extra minute while the activity is gated.
- **Decision**: ACCEPTED — applied to plan.md (Phase 1 time-skip rule: skip only while waiting, by `approval_deadline - await env.get_current_time(handle)`, no margin; the late-approval and downtime tests use it; release the gate promptly) and plan-brief.md (Tests row).

### F3 — Migration instructions preserve incompatible workflow histories

- **Severity**: WARNING
- **Impact**: LOW — correct the documented development reset.
- **Dimension**: Plan Completeness
- **Location**: Migration Notes (`plan.md:169`), Phase 2 README limitation (`plan.md:130`), and the brief's restart guidance.
- **Detail**: The plan says `docker compose down` followed by `up` clears the development server after the unversioned workflow change. SQLite is stored in the named `temporal-data` volume (`docker-compose.yml:28`, `docker-compose.yml:35`, `docker-compose.yml:48`). Ordinary `down` preserves that volume, so the incompatible histories remain. The [Docker Compose documentation](https://docs.docker.com/reference/cli/docker/compose/down/) specifies `--volumes` for removing named volumes.
- **Fix**: Document an explicit development reset with `docker compose down -v`, stating that it deletes all local ticket histories, and start the updated image afterward. Apply the same correction to the README contract and brief. This is documentation guidance; do not execute the reset as part of the review.
- **Decision**: ACCEPTED — applied to plan.md (Migration Notes and the Phase 2 README limitation: `docker compose down -v`, then `up`, deletes all local ticket histories; a plain `down` keeps them) and plan-brief.md (Key Decisions, Risks).
