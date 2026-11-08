# Real LLM Provider Behind a Setting — Plan Brief

> Full plan: `context/changes/real-llm-provider/plan.md`

## What & Why

Roadmap S-08 (FR-004, FR-009; issue #8). A reviewer can switch from the rule-based fake model to a real LLM using environment settings only. The real model must run through the same tool loop and the same rule checks as the fake. Fake mode stays the default, with no network and no key.

## Starting Point

- The tool loop (`agent.decide`) and the tool schemas already use OpenAI's message and function-tool shapes.
- `FakeChatModel` is the only model, and the worker hard-codes it.
- `Settings.from_env()` rejects any `LLM_MODE` other than `fake`, and the API calls it too, so the API can't start in real mode (review carry-over F8).
- S-07 added `ModelUnavailable` and its `llm_unavailable` escalation after 3 `decide` attempts.

## Desired End State

- `LLM_MODE=openai` with `LLM_BASE_URL` and `LLM_MODEL` (the key may be empty) makes the worker use one OpenAI-compatible adapter. That covers OpenAI, Azure OpenAI's v1 endpoint, OpenRouter and Ollama.
- Bad config stops the worker at startup with a named error. The API ignores LLM settings altogether.
- Provider errors:
  - errors a retry may fix are retried, then escalate with `llm_unavailable`;
  - a rejected request (bad key, unknown model, 400) escalates with `llm_unavailable` after one attempt.
- All 7 example tickets reach a final state against a real model. T-6 never gets a refund, and T-7 never reaches the model.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Provider | One OpenAI-compatible adapter (`openai` SDK), user has a key for a smoke run | One code path covers OpenAI, Azure OpenAI, OpenRouter and Ollama, and matches the README's Azure story and `.env.example`. |
| Errors a retry can't fix (400/401/403/404/422) | New `ModelRequestRejected` → non-retryable `llm_unavailable` | A person still sees the ticket, without three pointless calls on a bad key. |
| Errors a retry may fix (connection, timeout, 408/409/429/5xx) | `ModelUnavailable`, retried by `DECIDE_RETRY` | S-07's escalation path, unchanged. |
| Decision format | `response_format: json_object`, strict parser kept | One parser for fake and real, with no lenient extraction that injected text could game. |
| Bad config | Worker refuses to start; API ignores LLM settings | Caught before any ticket is touched, and fixes F8. |
| Retry layers | SDK `max_retries=0`, 20 s per call | Temporal is the only retry layer, inside the 60 s `decide` timeout. |
| Tests | `httpx.MockTransport` behind the real SDK | Exercises the real request and response code with no network. |

## Scope

**In scope:**
- `openai_llm.OpenAIChatModel`
- the `ModelRequestRejected` exception and the activity mapping for it
- the `LlmSettings` split and worker wiring
- no-network tests
- README "Real model" section and `.env.example` comments
- a smoke run with the user's key

**Out of scope:**
- an Anthropic-native adapter
- lenient JSON parsing
- falling back to fake mode
- configurable timeouts and limits
- the FR-016 comparison write-up (the smoke-run record feeds it later)
- usage or cost logging
- any workflow, API-route or fake-model change

## Architecture / Approach

The adapter is a sibling of `fake_llm.py` behind the existing `agent.ChatModel` seam, and the only module that imports `openai`. The loop and the business rules stay SDK-free. It turns SDK errors into `agent.ModelUnavailable` or `agent.ModelRequestRejected` (`from None`; only the SDK class name is kept as `error_type`). The `decide` activity turns those into `llm_unavailable`, retryable or not. `ESCALATE_ON_ERROR` already contains `llm_unavailable`, so the workflow doesn't change.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Real provider behind a setting | Adapter, error mapping, config split, worker wiring, stubbed-HTTP tests | Getting the SDK's message and error shapes right without a live call (mitigated by running the real SDK over `MockTransport`) |
| 2. Docs and a real-model smoke run | README and `.env.example`; 7 tickets against a real model, recorded | A real model may misread the JSON-only instruction, or a provider may reject `response_format` alongside tools |

**Prerequisites:** S-04 (rule checks) and S-07 (`llm_unavailable` path), both done. The user's provider key for Phase 2.
**Estimated effort:** about 1 session. Phase 1 is most of the code. Phase 2 is docs plus about 15 minutes of smoke testing.

## Open Risks & Assumptions

- Some OpenAI-compatible servers ignore or reject `response_format` together with `tools`. Such a provider escalates with `llm_unavailable` (400) or `unreadable_model_answer`. Phase 2 checks the user's provider.
- Real decisions may differ from the fake's expected outcomes for T-1 to T-7. That is acceptable: the rule checks bound them, and the README says so.
- The provider sees ticket text. This is a stated limitation, not handled.

## Success Criteria (Summary)

- A reviewer flips `LLM_MODE=openai` with three settings, and the same `docker compose up` processes tickets with a real model through the same checks.
- `uv run pytest` stays green with no network and no key.
- Every provider failure ends in an escalation with `llm_unavailable`. T-6 never refunds, and no log line carries a key, a provider message or ticket text.
