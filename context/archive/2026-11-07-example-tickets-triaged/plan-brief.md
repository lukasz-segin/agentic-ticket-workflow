# Remaining Example Tickets Triaged — Plan Brief

> Full plan: `context/changes/example-tickets-triaged/plan.md`

## What & Why

This is roadmap slice S-03. With no API key, T-3 must escalate as `technical` / `urgent`, T-4 must be answered citing KB-4 (`account` / `high`), and T-5 must close as `other` / `low`. T-7 (unknown customer C-999) must escalate with `unknown_customer` before the model is called (FR-004, FR-008, FR-009).

## Starting Point

The fake model has only the T-1 login rule, so T-3, T-4 and T-5 escalate as `no_matching_rule`. With a plain reply rule, T-4 would cite KB-3 (a tie broken by article ID). Nothing checks the customer before the model, and the workflow can't yet turn an activity error into an escalation.

## Desired End State

T-3, T-4, T-5 and T-7 reach the outcomes the PRD expects through the real activities. T-7 has no decision, a single `decide` attempt and one `unknown_customer` escalation. Tickets matching no rule still escalate.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| T-4 KB tie | Add the customer status from `get_customer` to the `search_kb` query | Mimics a real model using what its tools returned, and isn't tied to T-4, so FR-009 stays honest |
| T-5 close | Keyword rule (`pizza`, `lunch`, `restaurant`); tickets matching no rule still escalate | Unknown tickets keep reaching a person |
| T-7 check | `UnknownCustomer` in `agent.decide` → non-retryable `ApplicationError(type="unknown_customer")` → workflow escalates | Builds the error-to-escalation path once; S-07 adds its own codes |
| Error type ↔ reason | `ApplicationError.type` *is* the reason code; the workflow keeps one set of codes that escalate | A single place to extend, with no mapping table |

## Scope

**In scope:** three fake-model rules; the status in the KB query; a README note on the fake model's rules (FR-009); a guard test that T-2 and T-6 still match no rule; the customer check before the model; workflow escalation on `unknown_customer`; agent, workflow and real-activity tests.

**Out of scope:** `unreadable_model_answer` and `llm_unavailable` mapping (S-07); decision validation and refunds (S-04/S-05); changes to `search_kb` ranking; closing tickets that match no rule.

## Architecture / Approach

`agent.decide` (plain Python) checks the customer first and raises `UnknownCustomer`. The `decide` activity turns it into a non-retryable `ApplicationError`. The workflow catches `ActivityError` and escalates through the normal `act` step with `decision=None`. The fake-model changes stay inside `fake_llm.py`.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Fake-model rules | T-3, T-4 and T-5 decisions, plus updated agent tests | Keywords drifting toward example-tuning (FR-009 honesty) |
| 2. Unknown customer | T-7 escalated before the model, with no retries | Catching too broadly in the workflow; only codes in the set may escalate |

**Prerequisites:** S-01 done (it is).
**Estimated effort:** about 1 hour, one session, 2 phases.

## Open Risks & Assumptions

- The reason codes `possible_outage` and `not_support_request` are new names. The PRD fixes only category, priority and action for T-3 and T-5.
- The keyword `down` is a substring match. It's acceptable for the fake model, but it could match words like "download" in future sample tickets.

## Success Criteria (Summary)

- `uv run pytest` proves the T-3, T-4, T-5 and T-7 outcomes with no key and no network.
- With `docker compose up`, `GET /tickets/{id}` shows those outcomes. T-7 completes, with no failure and no retries.
