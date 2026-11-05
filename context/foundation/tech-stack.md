---
starter_id: fastapi
package_manager: uv
project_name: agentic-ticket-workflow
hints:
  language_family: python
  team_size: solo
  deployment_target: azure-container-apps
  ci_provider: github-actions
  ci_default_flow: manual-promotion
  bootstrapper_confidence: first-class
  path_taken: standard
  quality_override: false
  self_check_answers: null
  has_auth: false
  has_payments: false
  has_realtime: false
  has_ai: true
  has_background_jobs: true
---

## Why this stack

A solo developer is building a small Python API with a 1-week MVP and a hard deadline, so a mainstream, agent-friendly starter is the safest choice. FastAPI is the recommended default for Python APIs. It passes all four agent-friendly checks, and its Pydantic schemas fit the PRD's strict checks on every decision (allowed values; a refund only for the customer's own invoice, never above its amount). Scaffolding should work, though it may need an occasional manual step. FastAPI provides only the HTTP layer. Durable processing (asynchronous intake, the 24 h approval wait, retries without repeated actions, surviving restarts) runs on Temporal, with a separate worker, and the agent uses an LLM provider or a fake rule-based mode chosen by a setting. All of it runs locally with Docker Compose and no API key. Azure Container Apps is the deployment target described in the README, and optionally in IaC; nothing is actually deployed. CI uses GitHub Actions to run the tests on every push. Auth, payments and realtime are out of scope according to the PRD's Access Control and Non-Goals sections.

## Required technologies

The task requires these technologies; they must not be replaced or dropped:

- **Python** for the whole service.
- **FastAPI**, for the HTTP API: `POST /tickets`, `GET /tickets/{ticket_id}`, `POST /tickets/{ticket_id}/approval`.
- **Temporal**: the server with its web UI, a separate worker, workflows and activities written with the Python SDK (`temporalio`), and an activity retry policy with a limit.
- **An LLM with tool calling** (any provider and library). It needs at least the tools `get_customer`, `get_invoices` and `search_kb`, and a **fake LLM mode** chosen by an environment variable: no API key, no network, same output shape as the real model.
- **Docker Compose**: one `docker-compose.yml` that starts the Temporal server and its web UI, the API and the worker; `docker compose up` must work in fake LLM mode with no key.
- **Environment variables** for every setting and key, with a `.env.example` that holds no real secrets.
- **Structured logs** (JSON lines) from the API, the workflow and the activities, each with the ticket ID and the workflow ID.
- **Temporal's test environment** (`WorkflowEnvironment` with time skipping) for the workflow tests; all tests run with one command, with no network and no API key.

Optional extras (only if there is time):

- **GitHub Actions**, running the tests on every push.
- **OpenTelemetry** tracing across the API, the workflow and the activities.
- **Terraform or Bicep** for the Azure deployment.
- **Azure**: the deployment target, described in the README (services for the API, the workers, Temporal and the LLM; secrets; scaling; monitoring). Nothing is actually deployed.
