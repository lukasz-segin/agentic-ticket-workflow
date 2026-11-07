# AGENTS.md

## Sources of truth & hard rules

The product is defined in `context/`. Read these before you implement anything:

- `context/foundation/prd.md`: requirements (FR-001…FR-016), business rules, the expected outcome for each example ticket T-1…T-7, and the non-goals. It is the source of truth for behavior.
- `context/foundation/tech-stack.md`: the required technologies. Do not replace or drop them.
- `context/foundation/infrastructure.md`: the Azure Container Apps deployment that the README describes. Nothing is actually deployed.
- `context/changes/bootstrap-verification/verification.md`: the scaffold log.

`docs/` is gitignored and holds the original recruitment assignment, including the sample data (customers, invoices, KB articles, tickets). **The assignment text must never be committed.** Copy the sample data into the repo in any form you like, but leave the instructions out.

Hard deadline: 2026-11-07, with a budget of about 8 hours. Build only the must-have items FR-001–FR-012 until all of them pass. Start FR-013–FR-016 only after that. Locally, `docker compose up` must start at least the Temporal server, its web UI, the API and the worker (in fake LLM mode, no key). Supporting containers for Temporal itself (e.g. its persistence or a schema-setup step) are allowed. The application adds no database or queue of its own: ticket state lives in Temporal, and sample data stays as files in the repo. The described Azure deployment follows `context/foundation/infrastructure.md` instead (for example, the Temporal UI as a separate internal app, and PostgreSQL for Temporal).

## Commands

The project uses uv on Python 3.14, with a src layout and the `uv_build` backend. Manage dependencies only with uv (`uv add`, `uv add --dev`); never use `pip install`.

```sh
uv run agentic-ticket-workflow   # console script -> agentic_ticket_workflow:main
```

**Test command:** `uv run pytest` (all tests; no network and no API key, FR-011). The first run downloads Temporal's test server once and caches it.

**Lint/format:** `uv run ruff check` and `uv run ruff format --check` must pass before a commit (config in `pyproject.toml`). Fix with `uv run ruff check --fix` and `uv run ruff format`.

## Target architecture

These constraints come from the assignment and the PRD.

- **Layers stay separate:** HTTP API (FastAPI) → Temporal workflow → activities → outside services (LLM provider, fake Helpdesk API). The **business rules** (decision validation) must not import FastAPI, Temporal or any LLM SDK. They are plain Python and get unit tests.
- **Workflow per ticket (FR-001–FR-004).** The workflow ID comes from `ticket_id`, so a second `POST /tickets` for the same ID returns the existing workflow instead of processing the ticket twice. The steps are:
  1. Decide: an activity runs the LLM tool-calling loop with `get_customer`, `get_invoices` and `search_kb`, under a step limit.
  2. Validate in code.
  3. For refunds only, wait for an approval signal for up to 24 h.
  4. Act through the Helpdesk activity.

  The workflow keeps its current step, decision and result where they can be queried, for `GET /tickets/{id}`.
- **Unknown customer (FR-008):** T-7 is detected *before* the LLM is called. It escalates with `unknown_customer`.
- **Validation turns any rule breach into an escalation (FR-005)**, with the broken rule as the reason. The rules: allowed category, priority and action values. A refund must be for the same customer's own invoice, with an amount above 0 and no larger than that invoice. Ticket text is untrusted, so T-6 (prompt injection asking for 5000 EUR with no approval) must never get through.
- **Approval endpoint:** follows FR-006. Not found returns 404 and a conflict returns 409. A late approval must never issue a refund.
- **Retries (FR-007, FR-008):**
  - The LLM and Helpdesk activities have retry policies with a limit.
  - Errors a retry can't fix are non-retryable and escalate with a reason code: `unknown_customer`, `unreadable_model_answer` or `llm_unavailable`.
  - If the Helpdesk still fails after its last retry, the ticket **fails** with `helpdesk_unavailable`. It does not escalate.
  - Helpdesk actions must be idempotent, so a retried refund is issued exactly once.
- **Fake LLM mode (FR-009)**, chosen by an env var, is the default for `docker compose up` and for tests. It is simple and rule-based, needs no network, and returns tool calls and decisions in the same shape as the real model, so they go through the same loop and the same validation. The fake Helpdesk failure rate is also an env var.
- **Logs:** follow FR-010. Every ticket line carries `ticket_id` and `workflow_id`, and never the ticket body.
- **Tests:** FR-011 lists the required tests. Workflow tests use Temporal's `WorkflowEnvironment` with time skipping and fake activities.
- Settings and keys come only from env vars. `.env.example` must hold no real secrets. The project has no auth (stated as a known limitation).

## context/ conventions

See the README in each of `context/foundation/`, `context/changes/` and `context/archive/`.
