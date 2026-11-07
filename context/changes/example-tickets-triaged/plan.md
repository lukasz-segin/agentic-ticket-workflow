# Remaining Example Tickets Triaged Implementation Plan

## Overview

This is slice S-03. With no API key, T-3, T-4 and T-5 must get the decisions the PRD expects, and T-7 must escalate with `unknown_customer` before the model is called (FR-004, FR-008, FR-009). The work is three fake-model rules, one change to how the fake model searches, and a check on the customer before the model. The check produces an error, and the workflow turns that error into an escalation.

## Current State Analysis

- **Fake model:** `RULES` (`src/agentic_ticket_workflow/fake_llm.py:24`) holds only the T-1 login rule. T-3, T-4 and T-5 match no rule, so they escalate as `no_matching_rule`. A test pins that today: `tests/test_agent.py` `test_t5_escalates_with_no_matching_rule`.
- **KB tie for T-4:** the fake model calls `search_kb` with `subject + body`. For T-4 ("Account locked / Why can't we use the app anymore?"), KB-3 and KB-4 both score 1, on "account" alone. `search_kb` breaks ties by article ID (`tools.py:35`), so KB-3 would win. I checked: adding the customer's status (`suspended`) to the query ranks `['KB-4', 'KB-3']`, and T-1 with `active` still gets `KB-1` first.
- **T-7:** `get_customer("C-999")` returns `None` (`tools.py:16`), but the fake model carries on and the ticket escalates as `no_matching_rule`. Nothing checks the customer before the model is called.
- **Error handling:** `agent.decide` raises the plain `UnreadableModelAnswer`. The activity doesn't translate it, so Temporal retries it as a generic error. The workflow (`workflow.py:63`) has no try/except around `decide`, and nothing in `src/` uses `ApplicationError` yet. S-07 will map `unreadable_model_answer` and `llm_unavailable`. This slice builds the first error-to-escalation path, and S-07 extends it.
- **Status:** `TicketStatus.decision` is already `Decision | None` (`models.py:88`), so "no decision" needs no model change.

## Desired End State

All of these run with the fake model and no key:

| Ticket | Outcome |
| --- | --- |
| T-3 | `technical` / `urgent` / escalate, reason `possible_outage` |
| T-4 | `account` / `high` / reply citing `KB-4`; tools used: `get_customer`, `get_invoices`, `search_kb` |
| T-5 | `other` / `low` / close, reason `not_support_request` |
| T-7 | `decision` is `None` and `tool_calls` is `[]`; the helpdesk receives exactly one escalate with reason `unknown_customer`; `decide` runs once (no retries); the model is never called |

A ticket that matches no rule still escalates with `no_matching_rule`. Run as a whole, `uv run pytest` proves all of this.

### Key Discoveries:

- The fake model chooses its next step from the tool results it already has (`fake_llm.py:42-69`). `results["get_customer"]` is available when it builds the `search_kb` query, because `get_customer` is always called first.
- Rules are checked in order and the first match wins (`fake_llm.py:27`). The new keywords appear in none of T-1, T-2 or T-6.
- Lesson "Ticket text hides in derived payloads" (`context/foundation/lessons.md`): the new error and log lines carry only the reason code, never ticket text or model text.
- Layering (AGENTS.md): `agent.py` stays free of Temporal. The translation to `ApplicationError` belongs in `activities.py`.

## What We're NOT Doing

- Mapping `UnreadableModelAnswer` or LLM outages to escalations. That's S-07; this slice only leaves the place where S-07 adds them.
- Validating decisions or refund rules (S-04), and T-2/T-6 refund behaviour.
- Changing `search_kb` ranking or its ID tiebreak. The real tool stays as it is.
- Closing tickets that match no rule. They keep escalating, so a person sees them.
- Tuning priority from the customer's plan. Priority stays fixed per rule.

## Implementation Approach

Phase 1 is fake-model rules only. Phase 2 adds the customer check before the model: a plain-Python exception in `agent.decide`, which the activity translates into a non-retryable `ApplicationError` whose `type` is the reason code. The workflow catches it and escalates through the normal `act` step. One rule keeps the path ready for S-07: the error `type` *is* the reason code, and the workflow keeps one set of codes that escalate.

## Phase 1: Fake-model rules for T-3, T-4, T-5

### Overview

Three rules are appended to `RULES`, and the fake model's KB query adds the customer's status.

### Changes Required:

#### 1. Rules and the KB query

**File**: `src/agentic_ticket_workflow/fake_llm.py`

**Intent**: Give T-3, T-4 and T-5 their expected decisions while keeping the fake model simple and keyword-based. The fake model searches the KB using what `get_customer` told it, as a real model would, rather than a query tuned for each rule.

**Contract**:
- Append to `RULES`, after the login rule:
  - `("outage", "errors", "down")` → `technical` / `urgent` / `escalate`, reason `possible_outage`
  - `("locked", "suspended")` → `account` / `high` / `reply`, `needs_invoices=True`
  - `("pizza", "lunch", "restaurant")` → `other` / `low` / `close`, reason `not_support_request`
- The `search_kb` query becomes `f"{text} {status}"`. `status` is the `status` field of the `get_customer` result, or empty when it is missing or `None`.
- Update the module docstring. It currently says later slices "only append rules". It should say the query also includes the customer status.

#### 2. Agent tests for the example tickets

**File**: `tests/test_agent.py`

**Intent**: Pin the PRD outcomes for T-3, T-4 and T-5 through the real tool loop. Keep a test for the no-match fallback now that T-5 matches a rule.

**Contract**:
- A parametrized test over T-3, T-4 and T-5 that asserts category, priority and action type. It asserts `reason` only for T-3 and T-5 (escalate/close). `ReplyAction` has no `reason` (`models.py:25-29`). For T-4 it asserts `article_ids == ["KB-4"]` and tool names `["get_customer", "get_invoices", "search_kb"]`.
- Replace `test_t5_escalates_with_no_matching_rule` with the same assertion on a synthetic ticket for an existing customer (e.g. C-200) whose text matches no keyword.
- A guard test that T-2 and T-6 still escalate with `no_matching_rule`. The first matching rule wins, so a stray S-03 keyword would stop S-04's refund rules, added after it, from ever being reached.

#### 3. README note on the fake model

**File**: `README.md`

**Intent**: FR-009 says the README must state that fake mode is simple and rule-based. S-09 expects each slice to leave its README notes.

**Contract**: a short `### Fake model` subsection at the end of `## Run locally`. It says the fake model calls `get_customer`, then `get_invoices` when a rule needs it, then `search_kb` (with the customer status added to the query). The first keyword rule that matches wins. It lists the four rules as `keywords → category / priority / action`. It says a ticket matching no rule escalates with `no_matching_rule`. The limits: substring keyword matching, and rules written with the example tickets in mind.

### Success Criteria:

#### Automated Verification:

- Agent tests pass: `uv run pytest tests/test_agent.py`
- Full suite passes: `uv run pytest`
- Lint and format pass: `uv run ruff check` and `uv run ruff format --check`

#### Manual Verification:

- Reading `RULES` with the docstring still reads as "simple and rule-based" (FR-009): no ticket IDs and no article IDs in the rules
- The README's `### Fake model` note matches `RULES` and states the limits

**Implementation Note**: After automated verification passes, pause for manual confirmation before Phase 2.

---

## Phase 2: Unknown customer escalated before the model

### Overview

`agent.decide` checks the customer before the first model call. Failure travels as a non-retryable activity error typed `unknown_customer`, and the workflow escalates it without a decision.

### Changes Required:

#### 1. Plain-Python check

**File**: `src/agentic_ticket_workflow/agent.py`

**Intent**: Detect an unknown customer before the model runs (FR-008), so the outcome never depends on the model.

**Contract**: a new `class UnknownCustomer(Exception)` next to `UnreadableModelAnswer`. At the top of `decide`, before building messages, call `tools.get_customer(ticket.customer_id)`. If it returns `None`, raise `UnknownCustomer`, with a message that holds no ticket text.

#### 2. Activity translation

**File**: `src/agentic_ticket_workflow/activities.py`

**Intent**: Turn the plain exception into an error that Temporal will not retry, with the reason code as its type.

**Contract**: `decide` catches `agent.UnknownCustomer` and raises `ApplicationError(..., type="unknown_customer", non_retryable=True)` with `from None`. It logs one line with `reason_code` only.

#### 3. Workflow escalation

**File**: `src/agentic_ticket_workflow/workflow.py`

**Intent**: When `decide` fails with a known reason code, escalate with that code through the normal `act` step instead of failing the workflow. Any other error still propagates (S-07 adds more codes).

**Contract**:
- A module-level set of codes to escalate on, initially `{"unknown_customer"}`.
- Wrap the `decide` call in `try` / `except ActivityError` / `else`. The existing post-decision handling (`workflow.py:72-89`: storing `decision` and `tool_calls`, the "decision made" log line, the refund hold) moves into the `else:` branch, because `decided` is unset when the activity fails. In the `except` branch: if `err.cause` is an `ApplicationError` whose `type` is in the set, then `action = EscalateAction(reason=<type>)`. Leave `decision` as `None` and `tool_calls` as `[]`, log `escalated before decision` with `reason_code`, and go on to `_enter("acting")`. Otherwise re-raise.
- Steps stay `received → deciding → acting → done`, and the idempotency key stays `"{workflow_id}:escalate"`.

#### 4. Tests

**Files**: `tests/test_agent.py`, `tests/test_workflow.py`

**Intent**: Prove that the check runs before the model, that the workflow escalates without retrying, and that the whole chain works through the real activities.

**Contract**:
- `test_agent.py`: T-7 raises `UnknownCustomer`, and a model whose `complete` fails the test if called is never called.
- `test_workflow.py`: a fake `decide` that raises `ApplicationError(type="unknown_customer", non_retryable=True)` and counts its calls. Assert one call, `decision is None`, one act request with `EscalateAction(reason="unknown_customer")`, and step `done`.
- `test_workflow.py`: a test parametrized over T-3, T-4, T-5 and T-7 with the real `TicketActivities(FakeChatModel(), FakeHelpdesk(0.0))`. Assert the final `result.action` matches the Desired End State table.

### Success Criteria:

#### Automated Verification:

- Agent and workflow tests pass: `uv run pytest tests/test_agent.py tests/test_workflow.py`
- Full suite passes: `uv run pytest`
- Lint and format pass: `uv run ruff check` and `uv run ruff format --check`

#### Manual Verification:

- After `docker compose up`, `POST /tickets` with T-3, T-4, T-5 and T-7 from `src/agentic_ticket_workflow/data/tickets.json`; `GET /tickets/{id}` shows the outcomes in the Desired End State table
- In the Temporal UI, T-7's `decide` activity ran exactly one attempt, and the workflow completed rather than failed
- The worker logs for T-7 show `reason_code=unknown_customer` with `ticket_id` and `workflow_id`, and no ticket body

**Implementation Note**: After automated verification passes, pause for manual confirmation.

---

## Testing Strategy

### Unit Tests:

- Fake-model outcomes for T-3, T-4 (KB-4 wins once the status is in the query) and T-5. The no-match fallback, on a synthetic ticket. T-2 and T-6 still match no rule.
- `UnknownCustomer` is raised before any model call.

### Integration Tests:

- A time-skipped workflow escalates a non-retryable `unknown_customer` error after exactly one `decide` attempt.
- T-3, T-4, T-5 and T-7 run through the real activities, with the fake model and a helpdesk at 0% failure.

### Manual Testing Steps:

1. `docker compose up`, then POST T-3, T-4, T-5 and T-7.
2. GET each ticket and compare with the Desired End State table.
3. Check T-7's activity attempts in the Temporal UI, and check the log lines for the reason code.

## References

- Roadmap slice: `context/foundation/roadmap.md` → S-03
- PRD expected outcomes: `context/foundation/prd.md` (Business Logic table, FR-008, FR-009)
- Prior slice patterns: `context/archive/` (first-ticket-answered, ticket-traceable-in-logs)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Fake-model rules for T-3, T-4, T-5

#### Automated

- [x] 1.1 Agent tests pass: `uv run pytest tests/test_agent.py` — e9907db
- [x] 1.2 Full suite passes: `uv run pytest` — e9907db
- [x] 1.3 Lint and format pass: `uv run ruff check` and `uv run ruff format --check` — e9907db

#### Manual

- [x] 1.4 Reading `RULES` with the docstring still reads as "simple and rule-based" (FR-009): no ticket IDs and no article IDs in the rules — e9907db
- [x] 1.5 The README's `### Fake model` note matches `RULES` and states the limits — e9907db

### Phase 2: Unknown customer escalated before the model

#### Automated

- [x] 2.1 Agent and workflow tests pass: `uv run pytest tests/test_agent.py tests/test_workflow.py`
- [x] 2.2 Full suite passes: `uv run pytest`
- [x] 2.3 Lint and format pass: `uv run ruff check` and `uv run ruff format --check`

#### Manual

- [x] 2.4 After `docker compose up`, `POST /tickets` with T-3, T-4, T-5 and T-7 from `src/agentic_ticket_workflow/data/tickets.json`; `GET /tickets/{id}` shows the outcomes in the Desired End State table
- [x] 2.5 In the Temporal UI, T-7's `decide` activity ran exactly one attempt, and the workflow completed rather than failed
- [x] 2.6 The worker logs for T-7 show `reason_code=unknown_customer` with `ticket_id` and `workflow_id`, and no ticket body
