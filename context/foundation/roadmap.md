---
project: "Northdesk Agentic Ticket Workflow"
version: 1
status: active                   # draft | active | locked
created: 2026-11-06
updated: 2026-11-07
prd_version: 1
main_goal: speed
top_blocker: time
milestone_id: reviewer-ready-mvp
milestone_seq: 1
milestone_status: open           # open | done
---

# Roadmap: Northdesk Agentic Ticket Workflow

> Derived from `context/foundation/prd.md` (v1) + `shape-notes.md` (`## Forward: technical-roadmap`) + auto-researched codebase baseline.
> Edit-in-place; archive when superseded.
> Slices below are listed in dependency order. The "At a glance" table is the index.

## Milestone

**M-1: Reviewer-ready MVP** — Status: open

- **Intent:** Every must-have requirement works: all 7 example tickets run with no API key and reach a final state (or wait for refund approval) with a sensible decision, the rules hold against the ticket text, all tests pass with one command, and the README covers its checklist.
- **Source materials:** `context/foundation/prd.md` (v1), plus the build order parked in `context/foundation/shape-notes.md` → `## Forward: technical-roadmap`.
- **Done when:** every S-NN below is `done`. The nice-to-haves (FR-013–FR-016) are deliberately outside this milestone. AGENTS.md: "Start FR-013–FR-016 only after that."
- **Scope anchors:** FR-001–FR-012 (all must-have), US-01–US-04, the three Non-Functional Requirements, and the Business Logic expected-outcomes table for T-1…T-7.

## Vision recap

Northdesk's support team triages every ticket by hand. That means repetitive work, money at risk on refunds, and stalled processing whenever the AI or the helpdesk blips. This service processes each ticket as a multi-step, AI-assisted workflow. The ticket text can never bypass the business rules: exactly one checked action is carried out per ticket, never the model's unchecked one. Processing also survives brief LLM or helpdesk outages.

## North star

**S-01: Support agent submits ticket T-1 and watches it get answered automatically with the password-reset article** — this is the slice that proves the whole chain works (HTTP API → durable workflow → LLM tool loop → helpdesk). Every later slice reuses that chain, so with `main_goal: speed` it goes first.

> "North star" here means the smallest end-to-end slice whose successful delivery proves the product works. It is placed as early as its prerequisites allow, because everything else only matters if this works.

## At a glance

| ID   | Change ID                   | Outcome (user can …)                                                                                     | Prerequisites | PRD refs                                                | Status   | Issue |
| ---- | --------------------------- | -------------------------------------------------------------------------------------------------------- | ------------- | ------------------------------------------------------- | -------- | ----- |
| S-01 | first-ticket-answered       | Support agent can submit T-1, get its ID at once, and read its step, decision and KB-1 reply             | —             | US-01, FR-001, FR-002, FR-003, FR-004, FR-009, FR-011   | done     | [#1](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/1) |
| S-02 | ticket-traceable-in-logs    | Operator can follow one ticket through API, workflow and activity logs by ticket ID and workflow ID      | S-01          | FR-010                                                  | done        | [#2](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/2) |
| S-03 | example-tickets-triaged     | Support agent sees T-3, T-4, T-5 get their expected decisions and T-7 escalated as `unknown_customer`    | S-01          | FR-004, FR-008, FR-009                                  | done     | [#3](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/3) |
| S-04 | injection-escalated         | Support agent sees T-6's rule-breaking refund turned into an escalation naming the broken rule           | S-01          | US-03, FR-005, FR-011                                   | proposed | [#4](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/4) |
| S-05 | refund-approved-or-rejected | Support agent can approve or reject T-2's waiting refund; an approved refund is issued exactly once      | S-04          | US-02, FR-006, FR-007, FR-011                           | proposed | [#5](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/5) |
| S-06 | refund-timeout-escalated    | Support agent sees an unanswered refund escalated after 24 h, and a late approval refused                | S-05          | US-04, FR-006, FR-011                                   | proposed | [#6](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/6) |
| S-07 | failures-end-cleanly        | Support agent sees every ticket reach a final state under helpdesk/LLM failures, with a clear reason     | S-01          | FR-007, FR-008, FR-011                                  | proposed | [#7](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/7) |
| S-08 | real-llm-provider           | Reviewer can switch from the fake model to a real LLM provider with a setting                            | S-04          | FR-004, FR-009                                          | proposed | [#8](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/8) |
| S-09 | reviewer-readme-complete    | Reviewer can learn from the README how to run, call, test, understand and deploy the service             | S-02, S-03, S-06, S-07, S-08 | FR-012                                   | proposed | [#9](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/9) |

## Streams

Navigation aid: groups items that share a Prerequisites chain. Canonical ordering still lives in the dependency graph below; this table is the proposed reading order across parallel tracks. There are no Foundations, so every stream branches off the north star `S-01`.

| Stream | Theme                    | Chain                                   | Note                                                                                           |
| ------ | ------------------------ | --------------------------------------- | ---------------------------------------------------------------------------------------------- |
| A      | Money path               | `S-01` → `S-04` → `S-05` → `S-06`       | The required-scope chain with the most correctness risk; work it first under `speed`.               |
| B      | Example-ticket breadth   | `S-03`                                  | Joins Stream A at `S-01`; widens the fake model's rules to the remaining example tickets.     |
| C      | Resilience               | `S-07`                                  | Joins Stream A at `S-01`; parallel with A once the first flow exists.                         |
| D      | Operability & handoff    | `S-02` → `S-08` → `S-09`                | `S-02` joins at `S-01`, `S-08` at `S-04`; `S-09` closes the milestone once all streams land.  |

## Baseline

What's already in place in the codebase as of 2026-11-06 (auto-researched + user-confirmed).
The slices below assume these are present and do NOT re-scaffold them.

- **Frontend:** absent — by design (PRD Non-Goals: no UI; agents use the API and the workflow engine's own web UI).
- **Backend / API:** partial — HTTP framework and server declared in `pyproject.toml`; the container entrypoint names an API module and a worker module that do not exist yet; the workflow SDK is not yet a dependency; `src/agentic_ticket_workflow/__init__.py` holds only a hello-world `main()`.
- **Data:** absent — by design no application database (ticket state lives in the workflow engine). Sample customers, invoices, KB articles and example tickets exist only in the gitignored `docs/` and must be copied into the repo without the assignment text.
- **Auth:** absent — by design (PRD Access Control: no auth, stated as a known limitation).
- **Deploy / infra:** present — `Dockerfile`, `docker-compose.yml` (workflow engine dev server + web UI, api, worker), `.env.example`, README "Azure deployment" section (change `deployment`, all phases done). `docker compose up` cannot start api/worker until their modules exist. No CI.
- **Observability:** absent — no structured logging yet.
- **Tests:** absent — no test framework, no test command recorded in AGENTS.md.

## Foundations

None. The deploy layer is present, and each missing cross-cutting piece is introduced by the first slice that uses it: the workflow SDK dependency, the in-repo sample data, the fake model, the fake helpdesk and the test command in S-01, and structured logging in S-02. No missing piece would make S-01 unplannable or unverifiable on its own.

## Slices

### S-01: First ticket answered end-to-end

- **Outcome:** Support agent can submit ticket T-1 and get its ID back at once. Processing continues in the background: the fake model looks things up through the tool loop (`get_customer`, `get_invoices`, `search_kb`) and decides `account` / `normal` / `reply` citing KB-1. The reply is sent to the fake helpdesk exactly once, even with temporary helpdesk failures switched on (bounded retries plus an idempotency key). The agent can read the ticket's current step, decision and final result at any time. Resubmitting the same ticket ID returns the existing processing, including when that ticket has already finished or failed, so its action is never repeated. `docker compose up` brings this up with no API key, and the single test command runs a time-skipped workflow test for an answered ticket plus one HTTP API test.
- **Change ID:** first-ticket-answered
- **PRD refs:** US-01, FR-001, FR-002, FR-003, FR-004, FR-009, FR-011
- **Prerequisites:** —
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:**
  - Does the workflow engine's time-skipping test environment download a test-server binary on first run? If so, how is FR-011's "no network" kept (cached or pre-fetched binary)? — Owner: team. Block: no.
  - The fake model must stay simple and rule-based (FR-009) while still producing the expected-outcomes table. Decide its rule shape here, so S-03/S-04 only add rules. — Owner: team. Block: no.
- **Risk:** It carries the most wiring of any slice (intake, workflow, tool loop, helpdesk, status, test harness), but splitting it by layer would leave nothing working if time runs out. It is the north star, so it goes first.
- **Status:** done

### S-02: Ticket traceable in logs

- **Outcome:** Operator can follow one ticket through every log line from the API, the workflow and the activities by its ticket ID and workflow ID. Logs are machine-readable, one record per line, carry steps and decisions, and never the ticket body.
- **Change ID:** ticket-traceable-in-logs
- **PRD refs:** FR-010
- **Prerequisites:** S-01
- **Parallel with:** S-03, S-04, S-05, S-06, S-07, S-08
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Sequenced right after S-01, so later slices log through the same helper and don't need a retrofit. Risk: log calls inside workflow code must stay replay-safe. Carry-over from the S-01 review (F8): read `LOG_LEVEL`. It is set in compose and `.env.example`, but `worker.py` hardcodes INFO and the API configures no logging. Follow the lesson "Ticket text hides in derived payloads": never log `tool_calls`, decisions or model-text errors verbatim.
- **Status:** done

### S-03: Remaining example tickets triaged

- **Outcome:** Support agent sees T-3 escalated (`technical` / `urgent`), T-4 answered citing KB-4 (`account` / `high`), and T-5 closed (`other` / `low`). T-7 is escalated with `unknown_customer` before the model is consulted.
- **Change ID:** example-tickets-triaged
- **PRD refs:** FR-004, FR-008, FR-009
- **Prerequisites:** S-01
- **Parallel with:** S-02, S-04, S-05, S-06, S-07, S-08
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Mostly fake-model rules and the pre-model customer check. Risk: tuning the fake model to the examples so tightly that the README's "simple and rule-based" claim stops being honest (FR-009).
- **Status:** done

### S-04: Prompt injection escalated by the rules

- **Outcome:** Support agent sees T-6's proposed 5000 EUR refund turned into an escalation, with the broken rule (amount above the invoice) recorded as the reason in the ticket status. Every decision is checked against the allowed values and the refund rules (the customer's own invoice, amount above 0 and not above the invoice). The checks have unit tests.
- **Change ID:** injection-escalated
- **PRD refs:** US-03, FR-005, FR-011
- **Prerequisites:** S-01
- **Parallel with:** S-02, S-03, S-07
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Placed before any refund can be acted on, so no slice ever carries out the model's unchecked refund. The rules must stay plain code, independent of the HTTP, workflow and LLM layers (AGENTS.md).
- **Status:** proposed

### S-05: Refund approved or rejected by a person

- **Outcome:** Support agent sees T-2 waiting for approval with the proposed refund visible (INV-1002, 49.0 EUR). The agent can approve it, and the refund is then issued exactly once, even with helpdesk failures switched on. Or the agent can reject it, and the ticket then closes with no refund and the approver's comment as the reason. The optional approver name and comment are kept with the ticket. An approval for an unknown ticket is refused as not found, and an approval for a ticket that isn't waiting is refused as a conflict. The single test command runs a time-skipped workflow test for an approved refund.
- **Change ID:** refund-approved-or-rejected
- **PRD refs:** US-02, FR-006, FR-007, FR-011
- **Prerequisites:** S-04
- **Parallel with:** S-02, S-03, S-07, S-08
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Highest money risk in the product. The not-found/conflict refusal must happen before the approval reaches the workflow (shape-notes design note: an update validator), and the refund must reuse S-01's idempotency key.
- **Status:** proposed

### S-06: Unanswered refund escalated after 24 h

- **Outcome:** Support agent sees a refund with no approval or rejection within 24 h escalated, with the timeout as the reason and no refund issued. An approval sent after that is refused as a conflict and never issues a refund. The single test command runs a time-skipped workflow test for the 24 h timeout.
- **Change ID:** refund-timeout-escalated
- **PRD refs:** US-04, FR-006, FR-011
- **Prerequisites:** S-05
- **Parallel with:** S-02, S-03, S-07, S-08
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Kept separate from S-05 because a late approval is its own failure mode, with its own required test (FR-011 c). Its prerequisite is S-05, because the wait it times out is built there.
- **Status:** proposed

### S-07: Failures end cleanly with a reason

- **Outcome:** Support agent sees every ticket reach a final state when the outside services misbehave. A helpdesk that recovers within its retry limit carries out the action exactly once. A helpdesk still failing after its last retry fails the ticket with `helpdesk_unavailable`. A model that is unreadable, or that overruns the tool-loop step limit, escalates with `unreadable_model_answer`. A model still unavailable after its retry limit escalates with `llm_unavailable`. A restart in the middle of processing loses no ticket and repeats no action. The single test command runs a time-skipped workflow test for an action that fails and then succeeds after a retry.
- **Change ID:** failures-end-cleanly
- **PRD refs:** FR-007, FR-008, FR-011
- **Prerequisites:** S-01
- **Parallel with:** S-02, S-03, S-04, S-05, S-06, S-08
- **Blockers:** —
- **Unknowns:**
  - How fake mode simulates an unreadable or unavailable model for tests and demos (a setting, or test-only fakes), without the fake model growing beyond "simple". — Owner: team. Block: no.
- **Risk:** Covers the PRD guardrail "no endless retries", and the reviewer runs with a 30% helpdesk failure rate by default. Known limitation for the README: the fake helpdesk's idempotency memory is lost if the worker restarts.
- **Status:** proposed

### S-08: Real LLM provider behind a setting

- **Outcome:** Reviewer can switch from the fake model to a real LLM provider with environment settings only. The real model goes through the same tool loop and the same rule checks as the fake one, and fake mode stays the default with no network.
- **Change ID:** real-llm-provider
- **PRD refs:** FR-004, FR-009
- **Prerequisites:** S-04
- **Parallel with:** S-02, S-03, S-05, S-06, S-07
- **Blockers:** —
- **Unknowns:**
  - Which provider, and is a key available for a manual smoke run? `.env.example` already implies an OpenAI-compatible base URL, key and model. Without a key, this slice ships verified only against the fake and a stubbed provider. — Owner: user. Block: no.
- **Risk:** Follows S-04, so real-model output never reaches the helpdesk unchecked. Carry-over from the S-01 review (F8): the API calls `Settings.from_env()`, which rejects any `LLM_MODE` other than `fake`, so the API won't start in real mode until that check moves to the worker (or is replaced). It is placed late under `speed` because the default demo and all tests run in fake mode.
- **Status:** proposed

### S-09: Reviewer-ready README

- **Outcome:** Reviewer can learn everything on the FR-012 checklist from the README: how to run it with one command and how to run the tests; example requests for the three endpoints using the example tickets; the architecture with one simple diagram; why each part runs as a durable workflow step or as a call to an outside service; how retries, timeouts and duplicate requests are handled; how the rules are protected from ticket text; how AI assistants were used (with at least one wrong output and how it was noticed); and the assumptions, limitations and next steps. The Azure deployment section already exists.
- **Change ID:** reviewer-readme-complete
- **PRD refs:** FR-012
- **Prerequisites:** S-02, S-03, S-06, S-07, S-08
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:** —
- **Risk:** The PRD says to write it as the service is built, so each earlier slice should leave README notes and this slice finishes the checklist. The risk is leaving it to the end and running out of time.
- **Status:** proposed

## Backlog Handoff

| Roadmap ID | Change ID                   | Suggested issue title                                              | Ready for `/10x-plan` | Notes                               |
| ---------- | --------------------------- | ------------------------------------------------------------------ | --------------------- | ----------------------------------- |
| S-01       | first-ticket-answered       | T-1 answered end-to-end in fake-LLM mode (intake, status, tool loop) | done                  | Archived 2026-11-06 (PR #14)        |
| S-02       | ticket-traceable-in-logs    | JSON-line logs with ticket_id + workflow_id across API/workflow/activities | yes | Run `/10x-plan ticket-traceable-in-logs` |
| S-03       | example-tickets-triaged     | T-3/T-4/T-5 decisions + T-7 unknown_customer before the model       | yes | Run `/10x-plan example-tickets-triaged` |
| S-04       | injection-escalated         | Decision rule checks; T-6 refund escalates with the broken rule     | yes | Run `/10x-plan injection-escalated` |
| S-05       | refund-approved-or-rejected | T-2 refund waits for approve/reject; 404/409; refund exactly once   | no                    | After S-04                          |
| S-06       | refund-timeout-escalated    | 24 h approval timeout escalates; late approval refused             | no                    | After S-05                          |
| S-07       | failures-end-cleanly        | Bounded retries; helpdesk_unavailable / unreadable_model_answer / llm_unavailable | yes | Run `/10x-plan failures-end-cleanly` |
| S-08       | real-llm-provider           | Real LLM provider switchable by env setting                        | no                    | After S-04; key availability open   |
| S-09       | reviewer-readme-complete    | README covers the full FR-012 checklist                            | no                    | Last; closes the milestone          |

## Open Roadmap Questions

1. **Status quo (assumption).** The task never says how Northdesk handles tickets today; "manual triage" is an assumption, marked as such in Vision. — Owner: user. Block: no.
2. **Expected outcomes T-1…T-7 (assumption).** See the table in PRD Business Logic; notably T-2 refunds INV-1002, 49.0 EUR, and T-3 is `technical` / `urgent` / `escalate`. — Owner: user. Block: no (S-01, S-03, S-04, S-05 build to it).
3. **Rejected refund (assumption).** The task doesn't say what a rejection does; it closes the ticket with no refund, and the closing reason quotes the approver's comment. — Owner: user. Block: no (S-05).
4. **Refund amount above 0 (assumption).** The task only caps a refund at the invoice amount. — Owner: user. Block: no (S-04).
5. **No-network tests vs. the time-skipping test environment.** If the workflow engine's test environment fetches a binary on first run, "all tests with no network" (FR-011, NFR) needs a cached or pre-fetched binary, or a documented one-time setup step. — Owner: team. Block: no (settle in S-01's plan; S-05, S-06, S-07 rely on it).

## Parked

- **FR-013: tests on every push (CI)** ([#10](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/10)) — Why parked: nice-to-have; AGENTS.md says start FR-013–FR-016 only after FR-001–FR-012 pass. It is the first candidate for the next milestone (PRD: "first extra to do if time allows").
- **FR-014: one trace per ticket across API, workflow and activities** ([#11](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/11)) — Why parked: nice-to-have; overlaps FR-010 (S-02).
- **FR-015: infrastructure-as-code for the described Azure deployment** ([#12](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/12)) — Why parked: nice-to-have; it must match the README's Azure section exactly.
- **FR-016: real-vs-fake decision comparison** ([#13](https://github.com/lukasz-segin/agentic-ticket-workflow/issues/13)) — Why parked: nice-to-have; needs a real provider key and a manual run (after S-08).
- **Real helpdesk, payment system or money movement** — Why parked: PRD §Non-Goals.
- **Real customer database / data editing or import** — Why parked: PRD §Non-Goals; sample data stays as files in the repo.
- **UI or agent dashboard** — Why parked: PRD §Non-Goals; API plus the workflow engine's web UI only.
- **Auto-approved refunds (e.g. small amounts at higher volume)** — Why parked: PRD §Non-Goals; shape-notes notes it as a later idea for 100x volume.
- **Multi-action tickets (e.g. reply plus escalate for T-3)** — Why parked: PRD §Non-Goals.
- **Actual Azure deployment** — Why parked: PRD §Non-Goals; README description only.
- **Production-grade auth, roles, verified approvers** — Why parked: PRD §Non-Goals / Access Control; stated as a known limitation.
- **Scale and high-availability guarantees** — Why parked: PRD §Non-Goals.
- **Durable idempotency memory in the fake helpdesk (survives a worker restart)** — Why parked: shape-notes notes it as a README limitation, not MVP scope.

## Milestone History

## Done

- **S-01: Support agent can submit ticket T-1 and get its ID back at once. Processing continues in the background: the fake model looks things up through the tool loop (`get_customer`, `get_invoices`, `search_kb`) and decides `account` / `normal` / `reply` citing KB-1. The reply is sent to the fake helpdesk exactly once, even with temporary helpdesk failures switched on (bounded retries plus an idempotency key). The agent can read the ticket's current step, decision and final result at any time. Resubmitting the same ticket ID returns the existing processing, including when that ticket has already finished or failed, so its action is never repeated. `docker compose up` brings this up with no API key, and the single test command runs a time-skipped workflow test for an answered ticket plus one HTTP API test.** — Archived 2026-11-06 → `context/archive/2026-11-06-first-ticket-answered/`. Lesson: —.
- **S-02: Operator can follow one ticket through every log line from the API, the workflow and the activities by its ticket ID and workflow ID. Logs are machine-readable, one record per line, carry steps and decisions, and never the ticket body.** — Archived 2026-11-07 → `context/archive/2026-11-07-ticket-traceable-in-logs/`. Lesson: —.
- **S-03: Support agent sees T-3 escalated (`technical` / `urgent`), T-4 answered citing KB-4 (`account` / `high`), and T-5 closed (`other` / `low`). T-7 is escalated with `unknown_customer` before the model is consulted.** — Archived 2026-11-07 → `context/archive/2026-11-07-example-tickets-triaged/`. Lesson: —.
