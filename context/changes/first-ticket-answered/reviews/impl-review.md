<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: First Ticket Answered End-to-End (S-01)

- **Plan**: context/changes/first-ticket-answered/plan.md
- **Scope**: Full plan, Phases 1–3 of 3
- **Date**: 2026-11-06
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 4 warnings, 6 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | WARNING |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

## Success criteria evidence

- `uv lock --check`: pass ("Resolved 29 packages").
- `uv run pytest`: 16 passed in about 7 s.
- The grep for framework imports in the core modules: no matches.
- `import agentic_ticket_workflow.worker`: ok.
- `docker compose build`: image built.
- Manual items 1.4 to 3.6 are all ticked:
  - 1.4: verified. The data JSON was compared programmatically with the source arrays, and it contains no prose.
  - 3.6: verified. The README states the 24 h retention.
  - 2.3, 3.3, 3.4 and 3.5: these are runtime observations with no artifact in the diff. I accepted them as reported.

## Plan drift summary

Every contract item is MATCH. Two drifts are minor and not findings:
- fake_llm keys "already called" on the tool result messages, not on the assistant tool_calls. The behaviour is the same.
- The `run_ticket` docstring in test_workflow.py:32 is wrong. This is covered in F9.

The benign EXTRAs are:
- `Rule.reason`
- `asyncio.to_thread` in `decide`
- bad tool calls wrapped as `UnreadableModelAnswer`
- an extra README limitation bullet
- extra tests

## Findings

### F1 — HELPDESK_FAILURE_RATE does not behave as a failure rate

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/agentic_ticket_workflow/helpdesk.py:22-31
- **Detail**:
  - A known key returns at line 22, before the failure roll. So any "failure after recording" is always followed by a successful retry.
  - At `failure_rate=1.0` with 5 attempts, about 97 % of `act` activities still succeed. Only 0.5^5 ≈ 3 % exhaust their retries.
  - At the default 0.3, exhaustion is about 0.15^5 ≈ 0.008 %. That is not the PRD's ~0.2 % (0.3^5).
  - `.env.example` describes the setting as "probability that a call fails". It isn't, and the variable can't be used to reproduce or demo `helpdesk_unavailable` (FR-008, S-07).
  - The plan prescribed this shape ("a seen key returns the stored result with no failure roll"), so this is partly a plan flaw.
- **Fix A ⭐ Recommended**: Roll the failure first on every call, known keys included. If it hits a known key, raise without performing; otherwise keep the before/after coin flip. Each key is still recorded at most once.
  - Strength: The env var then means what `.env.example` says. Idempotency still holds (the action is recorded once), and S-07 gets a usable failure knob.
  - Tradeoff: You must update test_helpdesk.py's "same key twice" test, which assumes no roll on a repeat, by giving it rate 0. At 0.3 the retries become a little more frequent.
  - Confidence: HIGH. This is a three-line change in one function, and the tests already script the rng.
  - Blind spot: test_api.py uses rate 0, so it is unaffected. I haven't checked whether the README's "30 % failure" demo text implies a particular rate.
- **Fix B**: Keep the behaviour and document it. In `.env.example` and the README, say that the rate is per first attempt and that a failure after recording always recovers.
  - Strength: No code change.
  - Tradeoff: S-07 still needs a separate way to force exhaustion, such as a fake activity or a rate that is not really a rate.
  - Confidence: MED. It defers the problem to S-07.
  - Blind spot: The PRD's ~0.2 % claim stays wrong.
- **Decision**: FIXED (Fix A). Every call now rolls the failure, and a known key that fails raises without acting again. Added `test_known_key_can_still_fail_without_acting_again`. 17 tests pass.

### F2 — Temporal RPC failures surface as 500, and the 503 path swallows everything

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/agentic_ticket_workflow/api.py:50-58, 70-73, 79-82
- **Detail**:
  - POST catches only `WorkflowAlreadyStartedError`. Temporal being down, or a payload that is too large, gives an unhandled 500.
  - In GET, `describe()` (which has no `rpc_timeout`) re-raises any non-NOT_FOUND `RPCError` as a 500.
  - Two lines later, the query branch uses a bare `except Exception` that turns everything into a 503, bugs included, and logs nothing.
- **Fix**: Map `RPCError` UNAVAILABLE/DEADLINE_EXCEEDED to 503 in both handlers and give `describe` a short `rpc_timeout`. Narrow the query except to `WorkflowQueryFailedError | RPCError` and log a line with ticket_id and workflow_id.
- **Decision**: FIXED.
  - The `_temporal_unavailable` helper returns 503 and logs only the IDs and the error type.
  - `describe` now has a 5 s `rpc_timeout`.
  - The query except is narrowed to `WorkflowQueryFailedError | RPCError`.
  - Added `test_temporal_unavailable_returns_503`, which uses a stub client through monkeypatch. 18 tests pass.

### F3 — Ticket fields have no length limits

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/agentic_ticket_workflow/models.py:16-19
- **Detail**:
  - `customer_id`, `subject` and `body` only have `min_length=1`.
  - A body over Temporal's 2 MB payload limit makes `start_workflow` fail, and that is an unhandled 500 (F2).
  - Below that limit, the body is copied into the start event, into `DecideResult.tool_calls` (the search_kb query) and into GET responses. With S-08 it also costs unbounded LLM tokens.
- **Fix**: Add `max_length`: subject 200, body ~10 000, and a pattern or length cap on `customer_id` like the one on `ticket_id`.
- **Decision**: FIXED.
  - `Identifier` (the ticket_id pattern) now applies to `ticket_id` and `customer_id`.
  - Subject is capped at 200 and body at 10 000.
  - Added tests/test_models.py. 21 tests pass.

### F4 — Malformed tool calls escape as raw exceptions and echo model text

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/agentic_ticket_workflow/agent.py:50-58 (and tools.py:66)
- **Detail**:
  - Only `ValueError`/`TypeError` are wrapped. `search_kb` with `{"query": 123}` raises a bare `AttributeError`.
  - A call without `function`/`id` raises a bare `KeyError`. `call["id"]` is read only after the tool has run.
  - These escape as generic retryable errors, so S-07's `unreadable_model_answer` mapping will miss them.
  - The wrapped message also echoes the model-chosen tool name (`bad tool call 'X': unknown tool: X`). That text goes into Temporal history and the worker logs, and a steered real model could put ticket text there.
  - The fake model never triggers any of this. S-08 will.
- **Fix**: Validate each tool call with a small Pydantic model (id, name, arguments as a dict) before dispatch. Wrap any validation or tool exception in `UnreadableModelAnswer`, and don't echo the raw name (truncate it or omit it).
- **Decision**: FIXED.
  - `_RequestedCall` and `dict[str, str]` arguments are validated before dispatch.
  - Errors are wrapped as `bad tool call: <ErrorType>` with `from None`. The decision-parse error now also uses `from None`, because Temporal serializes the cause chain and a ValidationError cause carries the model's text.
  - Added a parametrized test with 4 cases. 25 tests pass.

### F5 — tool_calls carry the full ticket body (logging hazard for S-02)

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/agentic_ticket_workflow/fake_llm.py:71, models.py:82
- **Detail**:
  - The `search_kb` argument is subject + body. It is stored in `TicketStatus.tool_calls` and returned by GET.
  - That is fine today. But if S-02 logs `tool_calls` or decision arguments verbatim, it will break FR-010's "never the ticket body".
  - This is a recurring-rule candidate.
- **Fix**: Record as a lesson: "never log tool-call arguments or decision payloads verbatim; they may contain ticket text".
- **Decision**: FIXED + ACCEPTED-AS-RULE: Ticket text hides in derived payloads, not only in `body`. A warning comment was added on `ToolCall`.

### F6 — Worker ignores SIGTERM in the container

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/agentic_ticket_workflow/worker.py:37-38, docker-compose.yml
- **Detail**:
  - As PID 1 with no handler, Python ignores SIGTERM. `docker compose stop`/`restart` therefore waits 10 s and SIGKILLs the worker.
  - An `act` that is killed after recording but before completing is retried against a fresh, empty key store. That makes the documented double-action limitation more likely.
- **Fix**: Add `init: true` to the shared `x-app` compose anchor, or add a SIGTERM handler that calls `worker.shutdown()`.
- **Decision**: FIXED. Added `init: true` on `x-app`, and `docker compose config` shows it for both the api and the worker.
  - This removes the 10 s SIGKILL wait.
  - It is not a graceful drain: an in-flight `act` can still be cut off.
  - The stop timing was not measured at runtime.

### F7 — Pydantic is used directly but not declared

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: pyproject.toml:10-14
- **Detail**: models.py, agent.py and api.py import `pydantic`, and the data converter depends on it. Today it arrives only transitively, through FastAPI.
- **Fix**: `uv add pydantic`.
- **Decision**: FIXED. Ran `uv add pydantic`, which added `pydantic>=2.14.3`. The lock still resolves the same 29 packages, `uv lock --check` passes, and 25 tests pass.

### F8 — API validates worker-only settings; LOG_LEVEL never read

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: src/agentic_ticket_workflow/api.py:32, worker.py:18, config.py
- **Detail**:
  - The API calls `Settings.from_env()`, which rejects any `LLM_MODE` other than fake. The API itself never uses the LLM, so it would refuse to start once S-08 changes the mode, unless S-08 also fixes this.
  - `LOG_LEVEL` is set in compose and `.env.example` but never read. worker.py hardcodes INFO.
- **Fix**: Leave this to S-02/S-08. Read `LOG_LEVEL` in S-02. In S-08, drop the fake-only check or move it to the worker.
- **Decision**: SKIPPED (deferred to S-02 for LOG_LEVEL and S-08 for the LLM_MODE check).

### F9 — Test harness hygiene

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: tests/test_workflow.py:25,32, tests/test_api.py:16,24-25
- **Detail**:
  - The time-skipping `env` fixture is duplicated in two files.
  - test_api.py mutates the global `app.state` and never resets it, which will leak into future API tests.
  - The `run_ticket` docstring lists the wrong return values.
  - The GET query path for a running ticket and its 503 branch are untested.
- **Fix**: Move `env` to conftest.py, use a fixture that sets and restores `app.state`, and correct the docstring. Leave the extra coverage for later slices.
- **Decision**: FIXED.
  - The `env` fixture is now in conftest.py.
  - The API test sets `app.state` via monkeypatch.
  - The docstring is corrected.
  - Running-ticket query coverage is deferred. 25 tests pass.

### F10 — Roadmap still says S-01 in-progress; unrelated .gitignore change on branch

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Scope Discipline
- **Location**: context/foundation/roadmap.md:44,96, .gitignore:15
- **Detail**:
  - change.md says `implemented`, while the roadmap's S-01 row and section say `in-progress`.
  - `.gitignore` gained `.gemini/` in the p2 commit. It is unrelated tooling, harmless, but outside the plan.
- **Fix**: Set the roadmap S-01 status to done/implemented when closing the slice. Leave the .gitignore change as is.
- **Decision**: SKIPPED (the roadmap status is updated when the slice closes).

## Triage summary

| Outcome | Findings | Count |
|---------|----------|-------|
| Fixed | F1 (Fix A), F2, F3, F4, F6, F7, F9 | 7 |
| Fixed and recorded as a rule | F5 ("Ticket text hides in derived payloads, not only in `body`") | 1 |
| Skipped | F8 (deferred to S-02/S-08), F10 (at slice close) | 2 |

Verified after triage:
- `uv run pytest`: 25 passed.
- `uv lock --check`: OK.
- `docker compose config`: valid.
