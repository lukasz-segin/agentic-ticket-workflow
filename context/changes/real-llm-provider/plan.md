# Real LLM Provider Behind a Setting Implementation Plan

## Overview

This is roadmap slice S-08 (FR-004, FR-009; issue #8). A reviewer can switch from the fake model to a real LLM provider with environment settings only: `LLM_MODE=openai` plus `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY`. The provider is any OpenAI-compatible Chat Completions endpoint: OpenAI, Azure OpenAI (v1 endpoint), OpenRouter or Ollama. The real model plugs into the existing `agent.ChatModel` seam, so it runs through the same tool loop (`agent.decide`) and the same rule checks (`rules.py`, the `check` activity) as the fake one. Fake mode stays the default. Tests and `docker compose up` still make no network calls and need no key.

## Current State Analysis

- `src/agentic_ticket_workflow/agent.py` holds the provider-independent tool loop.
  - It expects `ChatModel.complete(messages, tools)` to return an OpenAI-shaped assistant message `{"role", "content", "tool_calls"}`, and it appends that message back into `messages` before the tool results.
  - `ModelUnavailable` exists, added in S-07: it is retryable and escalates with `llm_unavailable` after `DECIDE_RETRY`. `UnreadableModelAnswer` covers an unparseable decision, a bad tool call and the step limit.
- `src/agentic_ticket_workflow/tools.py` `TOOL_SCHEMAS` are already OpenAI function-tool definitions.
- `src/agentic_ticket_workflow/fake_llm.py` `FakeChatModel` is the only `ChatModel`. `src/agentic_ticket_workflow/worker.py:28` hard-codes it.
- `src/agentic_ticket_workflow/config.py` `Settings.from_env()` raises for any `LLM_MODE` other than `fake`. Both the worker and the API call it (`api.py:83`, `api.py:194`), so the API can't start in real mode even though it never calls the model. This is roadmap carry-over F8 from the S-01 review.
- `src/agentic_ticket_workflow/activities.py` `decide` runs `agent.decide` in `asyncio.to_thread`, so a blocking client call is fine. On `ModelUnavailable` it logs `error_type: type(exc).__name__`, which is always `"ModelUnavailable"`, and raises a retryable `ApplicationError(type="llm_unavailable")` with a fixed message, `from None`.
- `src/agentic_ticket_workflow/workflow.py` `decide_error_code` maps an `ActivityError` whose cause type is in `ESCALATE_ON_ERROR` (which contains `llm_unavailable`) to an escalation. Retryable and non-retryable causes are handled alike, because the cause is the last attempt's failure. The `decide` activity has a 60 s start-to-close timeout and 3 attempts.
- `.env.example` and `docker-compose.yml` already pass `LLM_MODE`, `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` to both containers.
- Runtime dependencies are fastapi, pydantic, temporalio and uvicorn. `httpx` is only a dev dependency. The `openai` SDK (3.46.0, Python ≥ 3.10) is not installed.
- The README's Azure table (`README.md:164`) already names Azure OpenAI and the three `LLM_*` settings, and Key Vault holds `LLM_API_KEY`.

## Desired End State

- `LLM_MODE=fake` (the default) behaves exactly as today.
- `LLM_MODE=openai` with `LLM_BASE_URL` and `LLM_MODEL` set makes the worker use `OpenAIChatModel`. `LLM_API_KEY` may be empty for keyless local servers.
- Bad configuration stops the worker at startup with a `ValueError` that names the variable:
  - an unknown `LLM_MODE`;
  - `openai` mode with `LLM_BASE_URL` or `LLM_MODEL` empty.
- The API starts whatever the `LLM_*` values are, because it no longer reads them.
- In real mode, each `decide` attempt calls the provider at most `max_steps` (6) times, with no SDK-level retries, a 20 s timeout per call and `response_format={"type": "json_object"}`. The assistant message passed back into the loop holds only `role`, `content` and `tool_calls`.
- Provider errors are mapped as follows:
  - **A retry may fix it** (connection error, timeout, HTTP 408, 409, 429, ≥ 500): `ModelUnavailable`. It is retried by `DECIDE_RETRY` and escalates with `llm_unavailable` once retries run out (as in S-07).
  - **A retry can't fix it** (any other HTTP error status, e.g. 400, 401, 403, 404, 422): the new `ModelRequestRejected`. The activity raises a **non-retryable** `ApplicationError(type="llm_unavailable")`, so the ticket escalates after one attempt.
  - Both log `error_type` as the SDK exception class name (e.g. `AuthenticationError`). They never log the provider's message, which may quote the request (lesson "Ticket text hides in derived payloads").
- A real-model answer that isn't valid JSON for `Decision` stays `unreadable_model_answer`. The parser stays strict, with no lenient extraction.
- `uv run pytest` passes with no network and no key. The provider is stubbed at the HTTP level with `httpx.MockTransport`.
- With a real key, all 7 example tickets reach a final state through compose. T-6 never gets a refund, and T-7 escalates with `unknown_customer` without any provider call.

### Key Discoveries:

- `openai.OpenAI(base_url=..., api_key=..., max_retries=0, timeout=20.0, http_client=httpx.Client(transport=...))` takes an injected `httpx.Client`. This is the seam the tests use. `max_retries` defaults to 2, so leaving it on would give 3 × 3 calls per ticket on an outage.
- `openai` exception hierarchy:
  - `APIConnectionError`, with subclass `APITimeoutError`: no response at all.
  - `APIStatusError`, with `.status_code` and subclasses `BadRequestError` (400), `AuthenticationError` (401), `PermissionDeniedError` (403), `NotFoundError` (404), `ConflictError` (409), `UnprocessableEntityError` (422), `RateLimitError` (429) and `InternalServerError` (≥ 500).

  Classify on `APIConnectionError` vs. `APIStatusError.status_code`, using the same retryable set the SDK itself retries (408, 409, 429, ≥ 500). Don't list every class.
- `client.chat.completions.create(...)` returns a typed `ChatCompletion`. `choices[0].message.model_dump()` carries extra keys (`refusal`, `annotations`, `audio`, `function_call`). Sending those back into `messages` can be rejected by stricter OpenAI-compatible servers, so build the dict from `role`, `content` and `tool_calls` only. Each tool call is `{"id", "type", "function": {"name", "arguments"}}`.
- `response_format={"type": "json_object"}` requires the word "JSON" somewhere in the messages. `agent.SYSTEM_PROMPT` already says "answer with only a JSON object".
- The SDK constructor raises `OpenAIError` when `api_key` is `None` and `OPENAI_API_KEY` is unset. An empty `LLM_API_KEY` therefore needs a non-empty placeholder (e.g. `"unused"`) so keyless servers work and the SDK never falls back to `OPENAI_*` env vars. Always pass `base_url` explicitly for the same reason.
- `ESCALATE_ON_ERROR` already contains `llm_unavailable`, and `decide_error_code` doesn't care about `non_retryable`. A non-retryable `llm_unavailable` therefore escalates with **no workflow change** (and no replay or versioning concern).

## What We're NOT Doing

- No Anthropic-native or other non-OpenAI-compatible adapter.
- No lenient decision parsing (code-fence stripping, JSON extraction from prose). A non-JSON answer stays `unreadable_model_answer`.
- No falling back to fake mode on bad config.
- No configurable timeout, step limit or retry count. `20 s`, `max_steps=6` and `DECIDE_RETRY` stay constants and the README states them.
- No FR-016 real-vs-fake comparison write-up. The Phase 2 verification note records the real decisions, so FR-016 can reuse them later.
- No token/usage or cost logging, and no model name in log lines.
- No change to `agent.decide`, `rules.py`, the workflow, the API routes or the fake model.
- No streaming, parallel-tool-call tuning or `tool_choice` settings. The provider's defaults apply.

## Implementation Approach

Keep `agent.py` provider-independent and add the provider as a sibling of `fake_llm.py`. The adapter is the only module that imports `openai`, so the business rules and the loop stay free of LLM SDKs (AGENTS.md layering). It turns SDK errors into the two `agent` exceptions with `from None`, and the activity turns those into reason codes, as S-07 does today. The LLM settings are split out of `Settings` into an `LlmSettings` that only the worker reads. That fixes F8 without the API learning about models, and it lets the worker fail fast on bad config. Tests stub the provider at the HTTP layer, so the real SDK code runs: request building, response parsing and error classes.

## Critical Implementation Details

- **Error-type logging:** the activity currently logs `type(exc).__name__`, which would always read `ModelUnavailable`. Give `ModelUnavailable` and `ModelRequestRejected` a keyword-only `error_type: str` attribute that defaults to the class's own name. The adapter sets it to the SDK class name, and the activity logs `exc.error_type`. The exception message must still never be logged or put into the `ApplicationError`: `tests/test_activities.py` `DownModel` puts a secret into it on purpose.
- **Catch order in the activity:** catch `ModelRequestRejected` and `ModelUnavailable` as separate `except` clauses. Neither is a subclass of the other.

## Phase 1: Real provider behind a setting

### Overview

Add the OpenAI-compatible `ChatModel`, map its errors, split the LLM settings so only the worker reads them, wire the worker, and cover it all with no-network tests.

### Changes Required:

#### 1. Dependency

**File**: `pyproject.toml`, `uv.lock`

**Intent**: Add the OpenAI SDK as a runtime dependency (`uv add openai`). `httpx` comes with it at runtime, and it stays a dev dependency for the API tests.

**Contract**: `openai>=3.46.0` in `[project].dependencies`.

#### 2. Agent exceptions

**File**: `src/agentic_ticket_workflow/agent.py`

**Intent**: Let a provider say "a retry can't fix this", and carry a safe error-type name for logs. The loop itself does not change.

**Contract**:
- `ModelUnavailable(message="", *, error_type: str | None = None)`, with `.error_type` defaulting to `"ModelUnavailable"`.
- New `ModelRequestRejected(Exception)` with the same constructor and docstring "the provider refused the request (bad key, unknown model, rejected input); a retry won't help".
- The `ChatModel.complete` docstring names both exceptions.

#### 3. OpenAI-compatible model

**File**: `src/agentic_ticket_workflow/openai_llm.py` (new)

**Intent**: Implement `ChatModel` over `openai.OpenAI().chat.completions.create`, returning the same message shape as `FakeChatModel`.

**Contract**:
- `OpenAIChatModel(base_url: str, model: str, api_key: str, *, http_client: httpx.Client | None = None)`. The client is built with `max_retries=0` and `timeout=CALL_TIMEOUT_SECONDS` (20.0), with a placeholder key when `api_key` is empty.
- `complete(messages, tools)` calls `create(model=..., messages=messages, tools=tools, response_format={"type": "json_object"})` and returns `{"role": "assistant", "content": str | None, "tool_calls": list[dict] | None}`. Each tool call is `{"id", "type": "function", "function": {"name", "arguments"}}`.
- An empty `choices` list raises `agent.UnreadableModelAnswer`.
- Error mapping, always `from None` and with `error_type=type(exc).__name__`:
  - `APIConnectionError`, or an `APIStatusError` with status in {408, 409, 429} or ≥ 500: `agent.ModelUnavailable`.
  - Any other `APIStatusError`: `agent.ModelRequestRejected`.

#### 4. Activity mapping

**File**: `src/agentic_ticket_workflow/activities.py`

**Intent**: A rejected request escalates at once. Both model errors log the provider's error type, never its message.

**Contract**:
- `except agent.ModelRequestRejected`: log `"model request rejected"` with `reason_code: llm_unavailable` and `error_type: exc.error_type`, then raise `ApplicationError("model request rejected", type=LLM_UNAVAILABLE, non_retryable=True) from None`.
- The existing `ModelUnavailable` branch logs `error_type: exc.error_type`.

#### 5. Settings split

**File**: `src/agentic_ticket_workflow/config.py`

**Intent**: The API stops depending on LLM settings (F8), and the worker validates them up front.

**Contract**:
- `Settings` loses `llm_mode` and no longer reads `LLM_MODE`.
- New `@dataclass(frozen=True) LlmSettings(mode: str, base_url: str, model: str, api_key: str)` with `from_env()`:
  - `LLM_MODE` defaults to `fake`; allowed modes are `("fake", "openai")`.
  - In `openai` mode, an empty `LLM_BASE_URL` or `LLM_MODEL` raises `ValueError` naming the variable. `LLM_API_KEY` may be empty.
  - Values are stripped.
- Error messages never include `LLM_API_KEY`'s value.

#### 6. Worker wiring

**File**: `src/agentic_ticket_workflow/worker.py`

**Intent**: Build the model from `LlmSettings` and fail at startup on bad config.

**Contract**:
- `build_model(llm: LlmSettings) -> ChatModel` returns `FakeChatModel()` or `OpenAIChatModel(llm.base_url, llm.model, llm.api_key)`.
- `main()` calls `LlmSettings.from_env()` right after `Settings.from_env()`, before connecting to Temporal, and passes `build_model(...)` to `TicketActivities`.
- The startup log line names the LLM mode, never the key or the base URL.

#### 7. Tests

**Files**: `tests/test_openai_llm.py` (new), `tests/test_config.py` (new), `tests/test_activities.py`, `tests/test_workflow.py`, `tests/test_api.py`

**Intent**: Prove the real adapter works through the same loop and maps errors correctly, with no network.

**Contract**:
- **`test_openai_llm.py`** uses an `httpx.MockTransport` that records requests and replies with scripted Chat Completions JSON.
  - `test_t1_decided_through_the_tool_loop_with_a_stubbed_provider`: one tool-call response, then a JSON decision content, through `agent.decide(tickets["T-1"], model)`. Asserts:
    - the decision parses;
    - each request body has `model`, `tools`, `response_format.type == "json_object"`;
    - the second request carries the assistant message (keys exactly `role`, `content`, `tool_calls`) before its `tool` result.
  - `test_provider_errors_map_to_model_exceptions`, parametrized:
    - a transport `httpx.ConnectError` or `httpx.ReadTimeout`, and statuses 408, 409, 429, 500, 503: `ModelUnavailable`;
    - statuses 400, 401, 403, 404, 422: `ModelRequestRejected`.

    In every case it asserts exactly one HTTP request (SDK retries off), that `error_type` is the SDK class name, and that a secret in the error response body is absent from `str(exc)` and `exc.__cause__ is None`.
  - `test_non_json_content_is_an_unreadable_answer`: prose content leads to `UnreadableModelAnswer` from `agent.decide`.
- **`test_config.py`**:
  - an unknown `LLM_MODE` and `openai` mode with an empty `LLM_BASE_URL` or `LLM_MODEL` raise `ValueError` naming the variable;
  - `fake` ignores the other `LLM_*` values;
  - `openai` with an empty key is accepted;
  - `Settings.from_env()` succeeds with `LLM_MODE=openai` and with `LLM_MODE=bogus` (the API ignores it);
  - `build_model` returns the right class for each mode.
- **`test_activities.py`**: a `RejectingModel` raising `ModelRequestRejected("401 ... {SECRET}", error_type="AuthenticationError")` produces `ApplicationError(type="llm_unavailable", non_retryable=True)` with no secret and no cause. Extend the existing parametrized test or add a sibling.
- **`test_workflow.py`**: `test_rejected_model_request_escalates_after_one_attempt`, using `run_with_model` with a counting rejecting model. The ticket is escalated with `llm_unavailable`, the model was called once, and `decision is None`.
- **`test_logs.py`** (or within the activity test): the `"model request rejected"` line carries `error_type: AuthenticationError` and `reason_code: llm_unavailable`, and no secret.

### Success Criteria:

#### Automated Verification:

- New adapter, config, activity, workflow and log tests pass: `uv run pytest tests/test_openai_llm.py tests/test_config.py tests/test_activities.py tests/test_workflow.py tests/test_logs.py`
- Full suite passes with no network and no key: `uv run pytest`
- Lint passes: `uv run ruff check`
- Format passes: `uv run ruff format --check`
- Only the adapter imports the SDK: `grep -rln "import openai\|from openai" src` lists only `openai_llm.py`

#### Manual Verification:

- `docker compose up --build` in default fake mode: T-1 is still answered citing KB-1, and the worker log names `fake` mode
- `LLM_MODE=openai` with `LLM_MODEL` empty: the worker exits with an error naming `LLM_MODEL`, while the API still starts and serves `GET /tickets/X` (404)

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Docs and a real-model smoke run

### Overview

Document how to switch providers and what happens when they fail, then run the example tickets against a real model with the user's key and record the results.

### Changes Required:

#### 1. README

**File**: `README.md`

**Intent**: A reviewer can switch to a real model from the README alone, and knows its failure behaviour and limits.

**Contract**:
- A new "Real model" subsection next to "Fake model". It covers:
  - `LLM_MODE=openai` and the three settings, with examples for OpenAI (`https://api.openai.com/v1`), Azure OpenAI (`https://<resource>.openai.azure.com/openai/v1/`, the deployment name as `LLM_MODEL`) and Ollama (`http://host.docker.internal:11434/v1`, empty key);
  - the `docker compose up` command, and that the worker refuses to start on bad config while the API doesn't care;
  - JSON mode, the 20 s per-call timeout, no SDK retries, and the step limit.
- The reason-code table and the S-07 paragraph: `llm_unavailable` now also covers a request the provider rejects (bad key, unknown model), which escalates after one attempt. "The fake model never fails" now reads that the fake can't fail, but a real provider can.
- Known limitations: real-model decisions can differ from the fake's expected outcomes. The rule checks still bound them. The provider sees the ticket text.

#### 2. `.env.example`

**File**: `.env.example`

**Intent**: Show the allowed modes and that the key may be empty for local servers, still with no real secret.

**Contract**: The comment lists `fake | openai` and one example `LLM_BASE_URL`. The values stay empty.

#### 3. Verification record

**File**: `context/changes/real-llm-provider/phase-2-manual-verification.md` (new)

**Intent**: Evidence of the smoke run. The recorded decisions can later feed FR-016.

**Contract**: The provider and model name (never the key), and per ticket: final status, step, action type, reason code. Plus the worker-log checks.

### Success Criteria:

#### Automated Verification:

- Full suite still passes: `uv run pytest`
- Lint passes: `uv run ruff check`
- Format passes: `uv run ruff format --check`
- `.env.example` holds no key: `grep -E "^LLM_API_KEY=$" .env.example`

#### Manual Verification:

- Real model via compose: all 7 example tickets (fresh IDs) reach a final state, each with a decision or a reason code
- T-6 under the real model never issues a refund: it is escalated with a rule code, or decided as a non-refund action
- T-7 escalates with `unknown_customer`: its worker log has an `"unknown customer"` line and no `"model decided"` line, and the provider was never called
- Worker logs for the run carry `ticket_id` and `workflow_id` and no ticket body, and contain no key, provider message or model output
- A deliberately wrong `LLM_API_KEY` escalates a fresh ticket with `llm_unavailable` after one `decide` attempt (Temporal UI), with `error_type: AuthenticationError` in the log

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Testing Strategy

### Unit Tests:

- Adapter request shape: model, tools, JSON response format, trimmed assistant message.
- Error classification across connection, timeout and every relevant status, with exactly one HTTP request each.
- Settings validation per mode, and the API settings ignoring the LLM settings.

### Integration Tests:

- `agent.decide` end to end over the real SDK against a stubbed HTTP provider (T-1).
- The activity turns a rejected request into a non-retryable `llm_unavailable`, and the workflow escalates after one attempt.

### Manual Testing Steps:

1. Fake-mode compose regression (T-1).
2. Bad config: the worker exits naming the variable, and the API stays up.
3. Real key: the 7 example tickets, recorded in the verification note.
4. Wrong key: an escalation with `llm_unavailable` after one attempt.

## Performance Considerations

A real `decide` makes up to 4 provider round trips per attempt (`get_customer`, `get_invoices`, `search_kb`, then the decision). At 20 s per call, a slow provider can hit the 60 s activity timeout. That is mapped to `llm_unavailable` by S-07's `decide_error_code`, which is acceptable.

## Migration Notes

None. Tickets are unaffected: the workflow code and its command sequence don't change. `LLM_MODE` defaults to `fake`.

## References

- Roadmap: `context/foundation/roadmap.md` S-08 (carry-over F8)
- Prior slice: `context/archive/2026-11-08-failures-end-cleanly/plan.md` (`ModelUnavailable`, `decide_error_code`)
- Seam: `src/agentic_ticket_workflow/agent.py` (`ChatModel`, `decide`), `src/agentic_ticket_workflow/fake_llm.py`
- Lesson: `context/foundation/lessons.md` "Ticket text hides in derived payloads"

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Real provider behind a setting

#### Automated

- [x] 1.1 New adapter, config, activity, workflow and log tests pass — bd2e091
- [x] 1.2 Full suite passes with no network and no key — bd2e091
- [x] 1.3 Lint passes — bd2e091
- [x] 1.4 Format passes — bd2e091
- [x] 1.5 Only the adapter imports the SDK — bd2e091

#### Manual

- [x] 1.6 Fake-mode compose still answers T-1 citing KB-1 and logs fake mode — bd2e091
- [x] 1.7 Missing LLM_MODEL stops the worker with a named error while the API still serves — bd2e091

### Phase 2: Docs and a real-model smoke run

#### Automated

- [x] 2.1 Full suite still passes
- [x] 2.2 Lint passes
- [x] 2.3 Format passes
- [x] 2.4 .env.example holds no key

#### Manual

- [x] 2.5 Real model: all 7 example tickets reach a final state
- [x] 2.6 T-6 under the real model never issues a refund
- [x] 2.7 T-7 escalates with unknown_customer without a model call
- [x] 2.8 Worker logs carry IDs and no ticket text, key, provider message or model output
- [x] 2.9 Wrong key escalates with llm_unavailable after one decide attempt
