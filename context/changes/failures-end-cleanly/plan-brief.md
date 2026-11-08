# Failures End Cleanly — Plan Brief

> Full plan: `context/changes/failures-end-cleanly/plan.md`

## What & Why

Roadmap slice S-07 (FR-007, FR-008, FR-011 d): every ticket reaches a final state with a clear reason when the model or the helpdesk misbehaves.

- A model that stays unreadable or unavailable after its retries escalates the ticket, so a person sees it.
- A helpdesk still failing after its last retry fails the ticket with `helpdesk_unavailable`.
- A worker restart in the middle of an action repeats nothing.

## Starting Point

Today an unreadable model answer, a hung model call and an exhausted helpdesk all fail the workflow with a raw `ActivityError`. A failed ticket shows `status: failed, step: acting` with no reason, and no log line carries `helpdesk_unavailable`, even though the README's alert section expects one. FR-011 (d), an action that fails and then succeeds on retry, is already tested.

## Desired End State

- Unreadable answers, including a step-limit overrun, escalate with `unreadable_model_answer` after 3 decide attempts.
- An unavailable model, or a call that times out, escalates with `llm_unavailable`.
- Any `act` failure moves the ticket to a new `failed` step with `failure_reason: helpdesk_unavailable`, visible in `GET /tickets/{id}`, the logs and the Temporal UI.
- A time-skipped test proves a worker restart mid-action performs the action exactly once.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Unreadable answers | Retryable; escalate after DECIDE_RETRY (3) | The PRD says "after a few attempts", and a real model often recovers on a second try. |
| What counts as `llm_unavailable` | Declared `agent.ModelUnavailable` + activity timeouts | The label stays honest, a hung provider is covered, and code bugs still fail loudly. |
| Simulating LLM failures | Test-only model doubles; production fake unchanged | No new settings and the fake stays simple; the README points to the tests. |
| Failed ticket visibility | `TicketStatus.failure_reason` + new `failed` step, read via the existing query | One status shape, no API logic change. |
| Which act failures → `helpdesk_unavailable` | Any `ActivityError` from `act` | `act` only talks to the helpdesk, and no failed ticket is left without a reason. |
| Restart proof | One time-skipped worker-restart test | Regression-tests the roadmap claim with no network. |
| Retry limits | Fixed constants (decide 3, act 5) | No settings for values nobody asked to tune. |

## Scope

**In scope:**
- `agent.ModelUnavailable`, the decide activity's error classification, and the workflow escalation mapping (including timeouts)
- The helpdesk failure path: `failure_reason`, the `failed` step, a log line and a typed workflow failure
- Tests: workflow (time-skipped), activity unit, API and logs; the restart test
- README: reason codes, retry limits, demo with `HELPDESK_FAILURE_RATE=1.0`

**Out of scope:**
- `LLM_FAILURE_RATE` or other fake-model failure modes
- Configurable retry limits
- Reason codes for code bugs in `decide` or `check`
- A persistent idempotency store
- Real provider error mapping (S-08)
- Workflow versioning

## Architecture / Approach

The activity classifies each error once, into a reason code in `ApplicationError.type`, and keeps it retryable when a retry might help. The workflow only sees the error after the retry policy gives up, so a single code set maps to an escalation. A final `TimeoutError` cause maps to `llm_unavailable`. On the act side, the workflow records the reason in its status before it raises a typed `ApplicationError`. The API's existing query path then shows it unchanged.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Model failures escalate | `unreadable_model_answer` / `llm_unavailable` escalations, tests, README | The time-skipping server may not time out an in-flight activity via `env.sleep`; the fallback is a unit test of the mapping. |
| 2. Helpdesk exhaustion fails cleanly | `failed` step + `failure_reason`, typed failure, API/log/restart tests, README | Restart test plumbing: the wait must use `await` (a blocking helpdesk double would stall the worker), plus sticky queue and cancellation on shutdown; proved with attempts `[1, 2]`, the same key and an independent execution counter |

**Prerequisites:** S-01 done (it is), with the time-skipping test server cached.
**Estimated effort:** about 1 session across 2 phases.

## Open Risks & Assumptions

- If an attempt hits a timeout, the last attempt's cause decides the code (for example, unreadable, unreadable, then timeout → `llm_unavailable`).
- A code bug inside `act` is also labelled `helpdesk_unavailable`; the logged stack frames tell it apart.
- The restart test shares one in-memory helpdesk between workers. A real process restart still loses keys (README known limitation).

## Success Criteria (Summary)

- No ticket ends in a failure without a reason code, except a code bug in `decide` or `check`, which is accepted.
- A support agent sees `llm_unavailable` / `unreadable_model_answer` as escalations, and `helpdesk_unavailable` as `failed` with a reason, in `GET /tickets/{id}`.
- `uv run pytest` covers every new path with no network and no key.
