# Northdesk Agentic Ticket Workflow - MVP ideas

### Core problem
The Northdesk support team receives many tickets every day (passwords, payments, outages, spam) and decides by hand what to do with each one. They need a backend that processes a ticket in several steps with the help of an AI agent, does not let the ticket's content bypass business rules, and keeps working when the LLM or other services fail temporarily.

### Smallest feature set
- Ticket intake through the API (`POST /tickets`): immediately returns an ID and starts a workflow; resending the same `ticket_id` returns the existing workflow instead of processing the ticket a second time
- AI agent decision with tool calling (`get_customer`, `get_invoices`, `search_kb`): category, priority and a single action (`reply`, `refund`, `escalate`, `close`)
- Decision validation in code: allowed values only; a refund only for an invoice belonging to the same customer and never above its amount; a decision that breaks a rule becomes an escalation to a human
- Human approval of refunds (`POST /tickets/{ticket_id}/approval`): no response within 24 h means escalation
- Action execution through a fake Helpdesk API that randomly returns transient errors (rate set by an environment variable); retries with a limit and no double execution of an action (e.g. a refund happens only once)
- Errors that retries will not fix (unknown customer, unreadable model output after several attempts) end in an escalation or a failure with a clear reason
- Ticket status view (`GET /tickets/{ticket_id}`): current step, decision and final result
- Fake LLM (rule-based) selected by an environment variable: works with no API key and no network, and returns tool calls and decisions in the same shape as the real model
- Structured logs (JSON lines) from the API, workflow and activities, with `ticket_id` and `workflow_id` on every line
- `docker compose up` starts Temporal (with the web UI), the API and the worker in fake LLM mode; `.env.example` with no real secrets
- Tests run with a single command, with no network and no key: workflow tests in Temporal's test environment (ticket reply, approved refund, refund waiting over 24 h, an activity that succeeds after retries), unit tests for the decision rules and at least one API test
- README: how to run, example requests, architecture with a diagram, retries and duplicates, protecting the rules from ticket content, Azure deployment (description), use of AI assistants, assumptions and limitations

### Constraints imposed by the task
- Python, FastAPI, Temporal, Docker Compose
- Separate layers: HTTP API, workflow, activities, business rules and external services (LLM, Helpdesk API); business rules do not depend on FastAPI, Temporal or the LLM provider
- Data (customers, invoices, knowledge base, sample tickets) lives in the repository in any simple form
- Budget: about 8 h of work, 3 days at most; simplicity over scope

### Out of scope for the MVP
- A real helpdesk system, real payments and refunds
- A real customer and invoice database (static data is enough)
- Authentication and authorization of API users
- A frontend or panel for the support team (approval through the API only)
- An actual Azure deployment (a description in the README is enough)

### Optional, if time allows (after the MVP is done)
- GitHub Actions running the tests on every push
- OpenTelemetry tracing across the API, workflow and activities
- Terraform or Bicep for the described Azure deployment
- Comparison of a real LLM with fake mode on the sample tickets: which decisions differ and why

### Success criteria
- `docker compose up` in fake LLM mode, with no API key, processes all 7 sample tickets (T-1 to T-7) to a final state or to waiting for approval
- The prompt injection attempt (T-6) never leads to a 5000 EUR refund or to skipping approval
- The unknown customer (T-7) ends in an escalation or a failure with a clear reason, not in endless retries
- With random Helpdesk API errors enabled, every action is executed exactly once
- All tests pass with a single command, with no network and no API key
- Every ticket can be traced in the logs by `ticket_id`
