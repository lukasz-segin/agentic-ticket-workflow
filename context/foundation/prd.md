---
project: "Northdesk Agentic Ticket Workflow"
version: 1
status: draft
created: 2026-11-05
context_type: greenfield
product_type: api
target_scale:
  users: small
  qps: low
  data_volume: small
timeline_budget:
  mvp_weeks: 1
  hard_deadline: 2026-11-07
  after_hours_only: false
---

# Northdesk Agentic Ticket Workflow — PRD

## Vision & Problem Statement

Northdesk's support team receives many tickets every day — password problems, billing questions, outages and some spam. *Assumption, not stated in the task: today the team reads, classifies and acts on each ticket by hand.* The cost is repetitive triage work on every ticket, money risk on refunds (a wrong or manipulated refund is paid out), and stalled processing whenever the AI or the helpdesk is briefly unavailable.

Insight (from the seed notes): ticket processing must be multi-step and AI-assisted, yet the ticket text must not be able to bypass the business rules, and processing must keep going when the LLM or other services fail for a moment. Pain categories: workflow friction, trust/safety, resilience.
## User & Persona

**Primary — Northdesk support agent.** Works in Northdesk's support team. Reaches for the product when tickets pile up: wants routine tickets (password resets, spam, known questions) handled automatically, and wants to be pulled in only for refund approvals and escalations.

### Secondary persona

**Assignment reviewer.** Clones the repository, starts everything with one command without any API key, runs the tests, sends the example tickets, reads the README, and asks for a small live change in a follow-up conversation.

## Success Criteria

MVP flow (the flow working = the product worked):

1. Reviewer starts the whole service with one command, in fake-LLM mode, with no API key.
2. Reviewer submits a ticket and immediately gets its ID back.
3. The agent decides — looking up customer, invoices and knowledge base as needed — a category, a priority and one action.
4. The decision is checked against the rules; a decision that breaks a rule becomes an escalation to a person.
5. Non-refund: the action is carried out in the (fake) helpdesk. Refund: it waits for a person to approve or reject; approved → the refund is issued; rejected → the ticket is closed with no refund; no answer within 24 h → escalation.
6. Reviewer reads the ticket's current step, decision and final result.

### Primary
- All 7 example tickets (T-1…T-7), run with no API key, each reach a final state or wait for refund approval, with a sensible decision.
- The rules hold against the ticket text: T-6 (prompt injection) never results in a 5000 EUR refund or a skipped approval; no refund ever exceeds the customer's own invoice.
- All tests pass with a single command, with no network and no API key.

### Secondary
- At least one item from the "if time allows" list is done (CI on push, tracing, infrastructure-as-code for the described Azure deployment, real-vs-fake LLM comparison).

### Guardrails
- No double actions: with random helpdesk failures switched on, every action — a refund above all — is carried out exactly once.
- No endless retries: errors a retry cannot fix (unknown customer as in T-7, an unreadable model answer after a few attempts, an LLM still unavailable after its retry limit) end in an escalation with a reason code, so a person sees the ticket. The one exception: a helpdesk still failing after its last retry fails the ticket with `helpdesk_unavailable` (FR-007).
- Traceable by ticket: every log line about a ticket carries the ticket ID and the workflow ID.
- No secrets in the repository; everything runs without a key.

## User Stories

### US-01: Password ticket is answered without a human

- **Given** ticket T-1 from an active customer (C-200) who forgot their password
- **When** the ticket is submitted
- **Then** it is answered with a reply based on the password-reset knowledge base article, and no person is involved

#### Acceptance Criteria
- Submitting returns the ticket ID immediately, before processing ends
- The ticket's status shows each step, the decision (category, priority, reply with the article it uses) and the final result
- The reply is sent exactly once, even if the helpdesk fails temporarily

### US-02: Double charge is refunded after approval

- **Given** ticket T-2 from customer C-100, who was charged twice for September
- **When** the ticket is processed and a support agent approves the proposed refund
- **Then** one refund for the duplicate September invoice, not larger than that invoice, is issued exactly once

#### Acceptance Criteria
- Expected decision *(assumption — the task doesn't define it)*: refund of INV-1002, 49.0 EUR, treating the later of the two identical September invoices as the duplicate
- Before approval, the ticket shows it is waiting for approval, with the proposed refund visible
- The approval may carry an approver name and comment, which are kept with the ticket
- A rejection means no refund is issued
- With random helpdesk failures switched on, the refund is still issued exactly once

### US-03: Prompt injection does not bypass the rules

- **Given** ticket T-6 from customer C-100 demanding a 5000 EUR refund "with no approval needed"
- **When** the ticket is processed
- **Then** no 5000 EUR refund is issued and no refund ever skips approval; a decision that breaks a rule becomes an escalation to a person

#### Acceptance Criteria
- A refund larger than the customer's invoice, or for another customer's invoice, is turned into an escalation with the broken rule as the reason
- The outcome is the same whatever the ticket text says about rules or approvals

### US-04: Unanswered refund is escalated

- **Given** a ticket whose refund is waiting for approval
- **When** no approval or rejection arrives within 24 hours
- **Then** the ticket is escalated to a person and no refund is issued

#### Acceptance Criteria
- An approval sent after the escalation is refused as a conflict (the ticket is no longer waiting) and does not issue a refund
- The status shows the timeout as the reason for escalation

## Functional Requirements

### Ticket intake & status
- FR-001: Support agent can submit a ticket and get its ID back at once, while processing continues in the background. Priority: must-have
  > Socrates: Counter-arguments considered: async response forces polling; malformed input accepted. Resolution: stands as written — required by the task.
- FR-002: Support agent can resubmit a ticket with the same ID without it being processed twice; they get the existing processing back. Priority: must-have
  > Socrates: Counter-arguments considered: changed content under the same ID is ignored; a failed ticket can't be reprocessed under its ID. Resolution: stands as written.
- FR-003: Support agent can see a ticket's current step, decision and final result at any time. Priority: must-have
  > Socrates: Counter-arguments considered: exposes model internals; unknown IDs. Resolution: stands as written.

### Decision
- FR-004: System can decide a category, a priority and one action (reply / refund / escalate / close) for a ticket. The model looks things up through tool calling with at least three tools — `get_customer` (plan and status), `get_invoices` (the customer's invoices) and `search_kb` (matching knowledge-base articles); each lookup the model asks for is carried out and its result given back, until the model returns its decision. The loop has a step limit; going over it counts as an unreadable model answer (FR-008). Priority: must-have
  > Socrates: Counter-arguments considered: one action is too few for e.g. an enterprise outage (T-3); each lookup is another failure point. Resolution: stands as written.
- FR-005: System can check every decision against the rules (allowed values; a refund only for the customer's own invoice, with an amount above 0 and not above the invoice amount) and turn any breach into an escalation, with the broken rule recorded as the reason — visible in the ticket status and in the logs. Priority: must-have
  > Socrates: Counter-argument accepted: "turning every breach into an escalation can hide a model that is often wrong." Resolution: revised — the broken rule is recorded as the escalation reason, so bad decisions stay visible.

### Refund approval
- FR-006: Support agent can approve or reject a waiting refund, with an optional name and comment; with no answer within 24 h the ticket is escalated. An approval for a ticket that doesn't exist is refused as not found; an approval for a ticket that isn't waiting for approval — not a refund, already approved or rejected, or past the 24 h wait — is refused as a conflict, so a late approval can never issue a refund. Priority: must-have
  > Socrates: Counter-arguments considered: anyone can approve (no auth); approval sent to a ticket that isn't waiting. Resolution: no-auth accepted in Access Control; non-waiting approvals resolved after shaping — refused as not found / as a conflict.

### Action & resilience
- FR-007: System can carry out the action in the helpdesk, retrying temporary failures up to a limit and never doing an action twice; when the retry limit is reached, the ticket fails with the reason `helpdesk_unavailable` (no fallback escalation). Priority: must-have
  > Socrates: Counter-argument accepted: "what happens to the ticket when retries run out?" Resolution: revised — exhausting retries fails the ticket with `helpdesk_unavailable`, never leaves it hanging. Chosen after shaping over an escalation fallback, to avoid extra code. Accepted cost: in that rare case (~0.2% at a 30% failure rate and 5 attempts) a person only sees the ticket by watching for failed tickets.
- FR-008: System can end a ticket with an unfixable error as an escalation with a reason code — `unknown_customer`, `unreadable_model_answer` or `llm_unavailable` (the LLM still failing after its retry limit) — without retrying forever, so a person always sees the ticket. An unknown customer is detected before the model is consulted, so the outcome doesn't depend on the model. Priority: must-have
  > Socrates: Counter-argument considered: "escalation OR failure" is ambiguous. Resolution: resolved after shaping — always an escalation with a reason code (the task allows "escalated or fails with a clear reason"). `llm_unavailable` added after shaping: the task requires a retry limit on the LLM call too, and the helpdesk is a separate service, so the escalation can still go out.

### Operability
- FR-009: Reviewer can start the whole service with one command and no API key (fake LLM mode), and switch to a real LLM provider with a setting. The fake mode is simple and rule-based, and the README says so. It returns tool calls and a decision in the same shape as the real model, so it runs through the same tool loop and the same rule checks. The helpdesk's temporary failure rate is also a setting. Priority: must-have
  > Socrates: Counter-argument accepted: "a fake LLM tuned to the 7 example tickets makes the demo look better than reality." Resolution: revised — keep the fake mode simple and rule-based and state its limits in the README.
- FR-010: Operator can follow one ticket through all logs by its ticket ID and workflow ID; logs are machine-readable, one record per line, come from the API, the processing steps and the actions, and carry IDs, steps and decisions, not the full ticket text. Priority: must-have
  > Socrates: Counter-argument accepted: "customer text in logs can be personal data." Resolution: revised — log IDs, steps and decisions; never the full ticket body.
- FR-011: Reviewer can run all tests with one command, with no network and no key. Required at least: processing tests with simulated time and fake actions for (a) a ticket that is answered, (b) a refund that is approved, (c) a refund that waits more than 24 h and is escalated, (d) an action that fails and then succeeds after a retry; unit tests for the decision checks (FR-005); at least one test of the service's external interface. Priority: must-have
  > Socrates: Counter-arguments considered: 24 h waits make tests slow; fakes test only the flow. Resolution: stands as written.
- FR-012: Reviewer can learn from the README how to run, call and test the service, how it is built, how it would be deployed to Azure (required by the reviewer — a documentation deliverable, not a stack choice), and how AI assistants were used, covering every item of the README checklist below (all required by the task). Priority: must-have
  - how to run the service with one command, and how to run the tests;
  - example requests for the three endpoints, using the example tickets;
  - architecture: the parts, how a ticket flows through them, one simple diagram;
  - why each part runs where it does (which parts are durable processing steps and which call outside services, and why);
  - how retries, timeouts and duplicate requests are handled;
  - how the rules are protected from what a ticket says;
  - Azure deployment: which Azure services run the API, the background processing, the workflow engine and the LLM; how secrets are stored; how it scales; what to watch in production;
  - how AI assistants were used, with at least one example where their output was wrong or needed changes, and how it was noticed;
  - assumptions, limitations, next steps.
  > Socrates: Counter-argument accepted: "that many README topics can eat a large part of ~8 h." Resolution: kept; written as the service is built, each topic short, with one simple diagram.

### If time allows (outside the MVP)
- FR-013: Reviewer can see the tests run automatically on every push. Priority: nice-to-have
  > Socrates: Counter-argument accepted: "cheapest extra once tests run with one command." Resolution: first extra to do if time allows.
- FR-014: Operator can follow one ticket as a single trace across the API, the processing steps and the actions. Priority: nice-to-have
  > Socrates: Counter-arguments considered: overlaps FR-010; needs a trace viewer. Resolution: stands as written.
- FR-015: Reviewer can create the described Azure deployment from infrastructure-as-code. Priority: nice-to-have
  > Socrates: Counter-argument accepted: "if done, it must match the README's Azure description exactly." Resolution: kept; consistency with the README is part of done.
- FR-016: Reviewer can read a comparison of real-LLM and fake-mode decisions on the example tickets, with reasons for each difference. Priority: nice-to-have
  > Socrates: Counter-argument accepted: "it requires a real provider key and a manual run." Resolution: kept; done only if a key is available.

## Non-Functional Requirements

- A restart of the service in the middle of processing loses no ticket and repeats no action; a refund that was waiting for approval is still waiting afterwards, with its 24 h deadline unchanged.
- With temporary helpdesk failures switched on at a configurable rate (e.g. 30%), every example ticket still reaches its final state (failing with `helpdesk_unavailable` counts as final), and each action is carried out exactly once.
- In fake-LLM mode, no request leaves the machine: the whole service and all tests run with no network access and no API key.

## Business Logic

Exactly one checked action is carried out per ticket, never the model's unchecked one.

Every ticket gets at most one decision from the agent (category, priority, one action). Every decision is checked against the allowed values and the refund rules (the invoice belongs to the same customer, and the amount is not larger than that invoice). Any decision that breaks a rule, and any valid refund that a person doesn't approve within 24 hours, is replaced by an escalation to a person. So exactly one checked action is carried out per ticket, never the model's unchecked one. *(user's wording; first clause reworded with the user's approval)*

Edge cases: a valid refund that a person rejects closes the ticket with no refund, and the closing reason quotes the approver's comment. An unknown customer, an agent answer that can't be read after a few attempts, or an agent still unavailable after its retry limit never yields a decision: the ticket is escalated with the reason code `unknown_customer`, `unreadable_model_answer` or `llm_unavailable`. A refund amount must also be above 0 *(assumption — the task only says "not larger than that invoice")*.

Expected outcomes for the example tickets *(assumptions — the task defines none of them)*:

| Ticket | Expected outcome |
| --- | --- |
| T-1 | `account` / `normal` / `reply` citing KB-1 |
| T-2 | `billing` / `normal` / `refund` INV-1002, 49.0 EUR (the later of the two identical September invoices is treated as the duplicate), then waiting for a person's approval |
| T-3 | `technical` / `urgent` / `escalate` — a reply can't fix an outage the system can't confirm |
| T-4 | `account` / `high` / `reply` citing KB-4 (account suspended, INV-4001 overdue) |
| T-5 | `other` / `low` / `close` — not a support request |
| T-6 | Whatever decision is proposed, no 5000 EUR refund is issued and no refund skips approval; a proposed refund above the invoice amount becomes an escalation with that broken rule as the reason |
| T-7 | No decision; escalated with `unknown_customer` before any decision is attempted |

Inputs the rule consumes: the ticket (customer ID, subject, body), the customer's plan and status, the customer's invoices, and the knowledge-base articles. Allowed values: categories `account`, `billing`, `technical`, `other`; priorities `low`, `normal`, `high`, `urgent`; actions `reply` (message + articles used), `refund` (invoice + amount), `escalate` (reason), `close` (reason). The support agent meets the rule through the ticket status (step, decision, reason) and through the approve/reject request for refunds.

## Access Control

No authentication in the MVP. All endpoints (submit ticket, read ticket status, approve/reject refund) are open; the service is assumed to run on a trusted internal network. This is stated as a known limitation, together with how it would be secured in production.

Flat model — no roles. Anyone who can reach the API can approve or reject a waiting refund. A refund approval/rejection carries an optional free-text approver name and comment, kept with the ticket's decision and in the logs as an audit trail; the name is not verified.

## Non-Goals

### Functional
- **No real helpdesk, payment system or money movement** — the helpdesk is simulated, with injected temporary failures.
- **No real customer database** — customers, invoices and knowledge-base articles are fixed sample data in the repository; no editing, no import.
- **No UI or agent dashboard** — agents view tickets and approve refunds through the API (and the workflow engine's own web UI).
- **No auto-approved refunds** — no refund is ever carried out without a person, not even a small one; auto-approving small refunds is a possible later change if approvals become the bottleneck at higher volume.
- **No multi-action tickets** — a ticket gets exactly one action; no reply-plus-escalate combinations (e.g. for the outage ticket T-3).
- **No actual Azure deployment** — the deployment is described in the README only; nothing is deployed (IaC is a nice-to-have, FR-015).

### Non-functional
- **No production-grade auth** — no accounts, roles or verified approvers (see Access Control).
- **No scale or high-availability guarantees** — no load targets, horizontal scaling or HA SLA for the MVP.

## Open Questions

No blocking questions remain. The entries below are assumptions the task does not define; they stand unless the task owner says otherwise.

1. **Status quo (assumption).** The task never says how Northdesk handles tickets today; "manual triage" is an assumption, marked as such in Vision. — Owner: user. Block: no.
2. **Expected outcomes T-1…T-7 (assumption).** See the table in Business Logic; notably T-2 refunds INV-1002, 49.0 EUR, and T-3 is `technical` / `urgent` / `escalate`. — Owner: user. Block: no.
3. **Rejected refund (assumption).** The task doesn't say what a rejection does; it closes the ticket with no refund, and the closing reason quotes the approver's comment. — Owner: user. Block: no.
4. **Refund amount above 0 (assumption).** The task only caps a refund at the invoice amount. — Owner: user. Block: no.

Resolved after shaping (2026-11-05): unfixable errors → escalation with reason code (FR-008); LLM still unavailable after its retry limit → escalation with `llm_unavailable` (FR-008); approval for a missing or non-waiting ticket → refused as not found / as a conflict (FR-006); helpdesk retries exhausted → ticket fails with `helpdesk_unavailable`, no fallback escalation (FR-007).

