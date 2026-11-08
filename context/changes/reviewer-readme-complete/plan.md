# Reviewer-Ready README Implementation Plan

## Overview

Finish FR-012 (roadmap S-09). Reorganise `README.md` so that each item of the FR-012 checklist has its own heading, then write the missing parts: an overview, the architecture with one Mermaid diagram, why each part runs where it does, all seven example tickets with a single command that submits them, one Reliability section for retries, timeouts and duplicate requests, how AI assistants were used (with two real examples of wrong output), and the assumptions, limitations and next steps. This change touches documentation only. No code changes.

## Current State Analysis

`README.md` (249 lines) holds a lot of correct and tested text, but it is ordered for running the service, not for the checklist. Design detail (decision rules, errors a retry can't fix, failed tickets) sits under `## Run locally`.

FR-012 coverage as of 2026-11-08:

| Checklist item | State |
| --- | --- |
| Run with one command; run the tests | ✅ `## Run locally`, `## Tests` |
| Example requests for the 3 endpoints using the example tickets | ◐ POST/GET with T-1, approval with T-2; T-3…T-7 missing |
| Architecture: parts, ticket flow, one diagram | ❌ missing |
| Why each part runs where it does | ❌ missing |
| Retries, timeouts, duplicates | ◐ correct but split over 4 places (intro line 29, `### Errors a retry can't fix`, `### Failed tickets`, `## Known limitations`) |
| Rules protected from ticket text | ◐ `### Decision rules`; T-6 not walked through |
| Azure deployment | ✅ `## Azure deployment` (complete; leave its content alone) |
| How AI assistants were used + wrong-output example | ❌ missing |
| Assumptions, limitations, next steps | ◐ limitations only; the PRD also asks how no-auth would be secured in production (`prd.md:189`) |

## Desired End State

A reviewer can open `README.md` and find each FR-012 checklist item under a heading with an obvious name, in this order:

1. Title plus a 2–3 sentence overview (what the service does and for whom; that the LLM proposes and code decides).
2. `## Quick start`: both start commands up front (`docker compose up --build` at the default 0.3 for the retry demo; `HELPDESK_FAILURE_RATE=0 docker compose up --build` to match the outcome table exactly), T-1 submit/read, the duplicate/404 note, a loop that submits all seven tickets and polls them to a stable step, a table of T-1…T-7 outcomes in fake mode, and then the T-2 approval walk-through (it approves the T-2 the loop left waiting, so it comes after the table).
3. `## Architecture`: the Mermaid diagram, the ticket flow by `step`, and a table of where each part runs and why.
4. `## Reliability`: retries, timeouts, duplicate requests, errors a retry can't fix, failed tickets, worker restarts.
5. `## Rules vs ticket text`: the decision rules table, T-6 as the worked example, and the approval/deadline rules.
6. `## Models`: fake model, real model.
7. `## Tests`.
8. `## Azure deployment` (unchanged).
9. `## How AI assistants were used`.
10. `## Assumptions, limitations and next steps`.

Verification: every internal `#anchor` link resolves, the Mermaid block renders on GitHub, and the submit loop pasted against `docker compose up --build` produces the outcomes the table claims.

### Key Discoveries:

- The workflow steps are `received → deciding → checking → awaiting_approval → acting → done | failed` (`src/agentic_ticket_workflow/models.py:17`). The diagram and the flow text should use these exact names.
- Activities: `decide` (LLM tool loop, 60 s, `DECIDE_RETRY` 3 attempts), `check` (refund rules on the data files, 10 s, `CHECK_RETRY` 3 attempts), `act` (helpdesk, 30 s, `ACT_RETRY` 5 attempts) (`workflow.py:33-35, 117, 148, 191`). The approval wait is a durable timer plus a Temporal Update with a validator (`workflow.py:161-169, 210-234`). The workflow code itself does no I/O; that is the "why each part runs where" argument.
- Duplicate requests: workflow ID `ticket-<id>` with `WorkflowIDReusePolicy.REJECT_DUPLICATE`, and `WorkflowAlreadyStartedError` → `200 created:false` (`api.py:107-109`). Idempotency key `ticket-<id>:<action>` for `act`.
- `unknown_customer` is raised non-retryable inside `decide` before the model is called (`activities.py:32-34`).
- Fake-mode outcomes are pinned by tests: T-3 `possible_outage`, T-5 `not_support_request`, T-7 `unknown_customer` (`tests/test_workflow.py:660-662`); T-6's check violation (`tests/test_workflow.py:345-356`). PRD expected outcomes: `prd.md:177-183`.
- Late-approval guard: `workflow.now() >= status.approval_deadline` in the validator (`workflow.py:234`), with regression test `test_approval_queued_during_worker_downtime_after_the_deadline_is_refused` (`tests/test_workflow.py:312`). Source: `context/archive/2026-11-07-refund-timeout-escalated/reviews/plan-review.md` F1.
- NaN fix: field-level serializer (`models.py:35-36`), test `test_non_finite_refund_crosses_temporal_and_is_escalated` (`tests/test_workflow.py:365`). The review's first suggested fix (`ser_json_inf_nan`) didn't work for nested models. Source: `context/archive/2026-11-07-injection-escalated/reviews/impl-review.md` F1.
- jq is not installed on the dev machine. The `api` image has Python and the packaged `data/tickets.json`, so the submit loop can run inside it and needs nothing on the host beyond Docker.
- PRD assumptions to list: manual triage today (`prd.md:22`), T-1…T-7 outcomes, a rejection closes the ticket with the comment, refund amount > 0, and a trusted network with no auth (`prd.md:209-214`, `prd.md:189`).
- Next-step candidates: FR-013 CI, FR-014 one trace, FR-015 IaC, FR-016 real-vs-fake comparison (roadmap `## Parked`), plus the README's own limitations (auth, durable helpdesk idempotency, workflow versioning, more workers).

## What We're NOT Doing

- No code, test, config or compose changes. If verification finds a mismatch between code and README, the README is corrected to match the code. A real bug found that way is reported, not fixed in this change.
- No rewrite of `## Azure deployment`. It may only move position and have its links fixed.
- No rewording of existing tested text beyond what merging the duplicate passages needs.
- No second diagram, no images, no separate docs pages.
- No FR-013…FR-016 work. They appear only as next steps.

## Implementation Approach

Two phases so a reviewer can check the restructure separately: Phase 1 moves text (diff shows moves and merges only), Phase 2 adds new prose and proves the claims live. Keep each new section short (PRD: "each topic short, with one simple diagram"). Prefer tables, which match the README's existing style.

## Phase 1: Restructure existing content

### Overview

Rearrange the current README under the target headings without losing any fact, and merge the scattered retry, timeout and duplicate text into one section.

### Changes Required:

#### 1. Heading skeleton and moves

**File**: `README.md`

**Intent**: Create the target headings (Desired End State, items 1–10) and move each existing passage under its new home. Leave empty placeholders where Phase 2 will fill in content (Overview, Architecture, the examples table, AI assistants, assumptions/next steps), each marked with an HTML comment `<!-- S-09 phase 2 -->`.

**Contract**: Mapping of today's sections to their new places:
- `## Run locally` intro, T-1 submit/read, duplicate/404 note, `### Approve a refund` → `## Quick start`.
- `### Fake model`, `### Real model` → `## Models`.
- `### Decision rules` → `## Rules vs ticket text` (its approval and deadline bullets stay with it).
- `### Errors a retry can't fix`, `### Failed tickets`, the worker-restart paragraph, the retention and in-memory-key limitations → `## Reliability` (limitations stay in the final list too, as short bullets linking back).
- `## Known limitations` → `## Assumptions, limitations and next steps` › `### Known limitations`. Keep that exact name: it preserves the `#known-limitations` anchor (README.md:145), and the Azure section already owns `### Limitations` (`#limitations`).
- `## Tests`, `## Azure deployment` unchanged.

#### 2. Reliability section

**File**: `README.md`

**Intent**: One section answering "how are retries, timeouts and duplicate requests handled", built from the moved text.

**Contract**: A table first, with one row per activity: `decide` / `check` / `act`, its timeout, its attempts and backoff, and what happens when it runs out. `decide`: escalate with a reason code (or fail on an unmapped error). `act`: fail with `helpdesk_unavailable`. `check` (10 s, 3 attempts, 1 s → 2 s) has no handler (`workflow.py:144-150`), so when it runs out the workflow fails with Temporal status `failed`, `step` still `checking`, and `failure_reason` null. Document that as it is. It also goes under Known limitations and gets a next step ("map `check` exhaustion to a reason code"). After it: subsections for duplicate requests (workflow ID + reuse policy + idempotency key + the 24 h retention caveat), errors a retry can't fix (the existing table), failed tickets (the existing text and demo), and worker restarts. Get the timeouts and attempt counts from `workflow.py:33-35, 117, 148, 191`; don't invent any.

#### 3. Anchor fixes

**File**: `README.md`

**Intent**: Every `](#...)` link points at a heading that exists after the move (e.g. `#approve-a-refund`, `#known-limitations`).

### Success Criteria:

#### Automated Verification:

- Every internal anchor resolves: a throwaway `uv run python` script in the session scratchpad (not committed) slugs each heading the way GitHub does (lowercase; punctuation and backticks dropped; spaces → hyphens; `-1`, `-2` suffixes for duplicate slugs) and reports every `](#x)` with no target
- Markdown-only diff: `git diff --stat` shows only `README.md`
- `uv run ruff check` and `uv run ruff format --check` still pass (sanity; no code touched)

#### Manual Verification:

- Side-by-side review: every fact in the old README is still present in the new one (no lost sentence other than merged duplicates)
- The Reliability table's timeouts and attempt counts match `workflow.py`

**Implementation Note**: After automated verification passes, pause for the human to confirm the restructure before Phase 2.

---

## Phase 2: New content and live verification

### Overview

Fill the placeholders and prove the example outcomes on a live compose run.

### Changes Required:

#### 1. Overview

**File**: `README.md`

**Intent**: 2–3 sentences under the title: an AI triage service for Northdesk support tickets. A model proposes a category, a priority and one action using three lookup tools. Code checks the proposal, a person approves refunds, and a fake helpdesk carries out the action. It runs locally with no API key.

#### 2. Architecture

**File**: `README.md`

**Intent**: Show the parts and how one ticket flows through them, then explain why each part runs where it does.

**Contract**:
- One ```` ```mermaid ```` `flowchart`: client → API (FastAPI) → Temporal server → worker running `TicketWorkflow`: `decide` (→ LLM fake/OpenAI-compatible, tools → data files) → `check` (→ data files) → `awaiting_approval` (← `POST /tickets/{ticket_id}/approval` as a Temporal Update) → `act` (→ fake helpdesk) → done/failed. `GET /tickets/{ticket_id}` reads the stored workflow result when the ticket has completed, and otherwise a workflow query, which needs a running worker (`api.py:132-142`). Label edges with the step names from `models.py:17`.
- A short numbered flow that names each `step` in order and the branches (non-refund skips the approval; a rule breach or an error a retry can't fix → escalate; helpdesk exhausted → failed).
- A table: part | where it runs | why. The workflow is durable, deterministic orchestration with no I/O, so it can replay after a crash and hold a 24 h timer. The activities are the only places that touch outside services (LLM, helpdesk, data files), so each gets its own timeout and retry policy. `check` is an activity, not workflow code, because it reads files. The API only starts, queries and updates workflows and holds no state. Temporal stores the ticket state, so the app adds no database (AGENTS.md).

#### 3. Example tickets

**File**: `README.md` › `## Quick start`

**Intent**: A reviewer can submit all seven example tickets in one paste and compare the result with a table.

**Contract**:
- One command that needs only Docker on the host: it runs Python inside the `api` container, reads the packaged `agentic_ticket_workflow/data/tickets.json`, POSTs each ticket to `localhost:8000/tickets`, and then polls `GET /tickets/{id}` with a bounded timeout (about 60 s) until every ticket is at `done`, `failed` or `awaiting_approval`. It prints `ticket_id`, `step`, the action type and the reason/violation, and reports any ticket still in flight when the timeout hits. Use Python's standard library only, so it adds no dependency. Submission is asynchronous (`202`), so an immediate single read-back is not enough.
- Prerequisite, stated above the command and pointing back to the rate-0 start command at the top of Quick start (so nobody has to restart halfway through): the table describes a fresh ticket history at `HELPDESK_FAILURE_RATE=0`; run `docker compose down -v` first if T-2…T-7 were submitted before. A ticket ID that was already used returns its earlier execution (`created: false`, `api.py:107-112`), so a T-1 submitted in the walk-through above is harmless, but a T-2 that was already approved shows `done`.
- A table T-1…T-7 → expected `step` / category / priority / action / reason in fake mode with `HELPDESK_FAILURE_RATE=0`, matching the PRD (`prd.md:177-183`) and the tests. T-2 stays at `awaiting_approval` and links to the approval walk-through that follows. T-6 links to `## Rules vs ticket text`.
- One note on the default `HELPDESK_FAILURE_RATE=0.3`: retries make tickets take longer, and a ticket can occasionally end at `failed` with `failure_reason: helpdesk_unavailable` and `result: null` (`workflow.py:194-201`). Waiting doesn't recover it. Link to the failed-tickets part of `## Reliability`.
- The T-2 approval walk-through comes after the table and approves the waiting T-2. Its own submit step stays and returns `created: false` when the loop already submitted T-2.

#### 4. Rules vs ticket text: T-6 walk-through

**File**: `README.md`

**Intent**: Use the injection ticket to make the protection concrete: the fake model obeys "refund 5000 EUR" on purpose, `check` reads the invoice from the data file, finds the amount above the invoice and escalates with `refund_amount_above_invoice`, and no refund is ever acted on. Even a valid refund still needs a person. Show the actual `violation` and `result` fields from the live run.

#### 5. How AI assistants were used

**File**: `README.md`

**Intent**: Say honestly how the project was built with AI and give two examples where the output was wrong, how each was noticed, and what changed.

**Contract**:
- Roles: Claude Code did shaping, PRD, roadmap, per-slice plans and implementation through the 10x skills (`.claude/skills/`). Gemini and OpenAI Codex/ChatGPT acted as independent plan and implementation reviewers. The human triaged every finding (ACCEPTED/FIXED decisions recorded in `context/archive/*/reviews/`). Name `context/` as the place where the trail lives.
- Example 1 (late approval, S-06): the AI-written plan let an approval that was queued during worker downtime issue a refund after the 24 h deadline, because the Temporal SDK applies Updates before timers in the same activation. The plan review noticed it by reading the SDK source. The fix: the validator refuses when `workflow.now() >= approval_deadline`, with a regression test that fails without the check (name it).
- Example 2 (NaN refund, S-04): the implementation turned a NaN amount into JSON `null` at the Temporal converter, so the activity result failed to decode and the workflow hung (the rule unit test passed and missed it). The review caught it, and its suggested fix (`ser_json_inf_nan`) also turned out wrong for nested models. That was noticed when the regression test still timed out, and it was replaced with a field serializer (name the test).
- One line on the takeaway: reviews and boundary-crossing tests caught what unit tests didn't.
- Keep it to about 20–25 lines.

#### 6. Assumptions, limitations and next steps

**File**: `README.md`

**Intent**: Complete the last checklist item.

**Contract**:
- `### Assumptions`: the PRD assumptions (manual triage today; T-1…T-7 expected outcomes, notably T-2 → INV-1002 49.0 EUR and T-3 escalate; a rejection closes the ticket with the comment; refund > 0; a trusted internal network).
- `### Known limitations` (this exact name, see Phase 1 §1): the existing list, plus the `check`-exhaustion bullet from Phase 1 §2. Extend the no-auth bullet with how it would be secured in production: Entra ID / OAuth2 bearer tokens on the API, approvals restricted to a role with the approver taken from the token instead of the request body, and the API kept behind private ingress or API Management.
- `### Next steps`: FR-013 CI on push, FR-014 one trace per ticket, FR-015 IaC for the Azure section, FR-016 real-vs-fake comparison, auth as above, helpdesk idempotency kept on the helpdesk side, workflow versioning (patching) before changing workflow code, more than one worker once idempotency is durable, and mapping `check` exhaustion to a reason code.

#### 7. Remove placeholders

**File**: `README.md`

**Intent**: No `<!-- S-09 phase 2 -->` markers remain.

### Success Criteria:

#### Automated Verification:

- No placeholders left: `grep -c "S-09 phase 2" README.md` returns 0
- Every internal anchor resolves (same scratchpad slug script as Phase 1, duplicate suffixes included)
- Only docs changed: `git diff --stat main` lists `README.md` plus context files only
- `uv run pytest` passes (sanity; unchanged code)

#### Manual Verification:

- On a fresh `HELPDESK_FAILURE_RATE=0 docker compose up --build` (fake mode, after `docker compose down -v`), the README's submit-and-poll command ends with the outcomes in the T-1…T-7 table (T-2 at `awaiting_approval`, T-6 `refund_amount_above_invoice`, T-7 `unknown_customer`) before T-2 is approved
- The T-6 JSON excerpt in the README matches the live response
- The Mermaid diagram renders on GitHub (or in the VS Code Markdown preview with Mermaid support)
- Each FR-012 checklist bullet (`prd.md:138-146`) can be pointed to under a named heading
- The AI section's facts match the archived reviews and the named tests exist

**Implementation Note**: After automated verification passes, pause for the human to confirm the live run and review the AI section before closing.

---

## Testing Strategy

### Unit Tests:

- None added. This change is docs only. `uv run pytest` runs as a regression sanity check.

### Integration Tests:

- The live compose run in Phase 2 is the integration check for the README's examples.

### Manual Testing Steps:

1. `docker compose down -v`, then `HELPDESK_FAILURE_RATE=0 docker compose up --build`.
2. Paste the submit-and-poll command from `## Quick start` and wait for it to finish (all tickets stable or the timeout reported).
3. Compare each row with the T-1…T-7 table **before** approving anything. Then approve T-2 with the documented curl and see `done` with a refund.
4. Open the README on GitHub (branch view) and check the diagram and every heading link.

## References

- PRD FR-012: `context/foundation/prd.md:137-147`; expected outcomes `prd.md:173-183`; assumptions `prd.md:209-214`
- Roadmap S-09: `context/foundation/roadmap.md` › `### S-09`
- Wrong-output sources: `context/archive/2026-11-07-refund-timeout-escalated/reviews/plan-review.md` (F1), `context/archive/2026-11-07-injection-escalated/reviews/impl-review.md` (F1)
- Lesson: `context/foundation/lessons.md` (ticket text in derived payloads; the T-6 example must quote only code-produced fields, never the ticket body in logs)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Restructure existing content

#### Automated

- [x] 1.1 Every internal anchor resolves
- [x] 1.2 Markdown-only diff
- [x] 1.3 Ruff check and format still pass

#### Manual

- [x] 1.4 No fact from the old README lost
- [x] 1.5 Reliability table matches workflow.py

### Phase 2: New content and live verification

#### Automated

- [ ] 2.1 No placeholders left
- [ ] 2.2 Every internal anchor resolves
- [ ] 2.3 Only docs changed
- [ ] 2.4 uv run pytest passes

#### Manual

- [ ] 2.5 Live submit-and-poll at failure rate 0 matches the T-1…T-7 table
- [ ] 2.6 T-6 excerpt matches the live response
- [ ] 2.7 Mermaid diagram renders
- [ ] 2.8 Every FR-012 checklist bullet maps to a heading
- [ ] 2.9 AI section facts match archived reviews and named tests
