# agentic-ticket-workflow

## Run locally

```sh
docker compose up --build
```

This starts the Temporal dev server, the Temporal UI at <http://localhost:8233>, the API at <http://localhost:8000>, and the worker. No `.env` and no API key are needed: the model runs in fake mode (`LLM_MODE=fake`), and the fake helpdesk fails 30 % of calls (`HELPDESK_FAILURE_RATE=0.3`) so that you can see retries.

Submit ticket T-1. The API answers `202` at once, and processing continues in the background:

```sh
curl -X POST localhost:8000/tickets -H 'content-type: application/json' --data-binary @- <<'EOF'
{"ticket_id": "T-1", "customer_id": "C-200", "subject": "Can't log in",
 "body": "I forgot my password and can't get into my account."}
EOF
# {"ticket_id":"T-1","workflow_id":"ticket-T-1","created":true}
```

Read its status, step, decision and result:

```sh
curl localhost:8000/tickets/T-1
# {"status":"completed","step":"done","decision":{"category":"account","priority":"normal",
#  "action":{"type":"reply","article_ids":["KB-1"],...}},"result":{...,"helpdesk_ref":"HD-1"},...}
```

Submitting the same `ticket_id` again returns `200` with `"created": false`, whether that ticket is still running or has already finished. The ticket is never processed twice. An unknown ID returns `404`. Open `ticket-T-1` in the Temporal UI to see the `decide`, `check` and `act` activities and any `act` retries.

### Approve a refund

A refund is never issued without a person. Submit T-2 (a double charge), and it stops at `awaiting_approval` with the proposed refund in `decision`:

```sh
curl -X POST localhost:8000/tickets -H 'content-type: application/json' --data-binary @- <<'EOF'
{"ticket_id": "T-2", "customer_id": "C-100", "subject": "Charged twice",
 "body": "We were charged twice for September. Please refund the extra payment."}
EOF
curl localhost:8000/tickets/T-2
# {"status":"running","step":"awaiting_approval","decision":{...,"action":{"type":"refund",
#  "invoice_id":"INV-1002","amount_eur":49.0}},"result":null,...}
```

Approve it (`approver` and `comment` are optional). The API answers `200` as soon as the answer is recorded, and the workflow then issues the refund:

```sh
curl -X POST localhost:8000/tickets/T-2/approval -H 'content-type: application/json' \
  -d '{"approved": true, "approver": "Ann", "comment": "duplicate confirmed"}'
# {"ticket_id":"T-2","workflow_id":"ticket-T-2","approved":true}
```

`{"approved": false, ...}` rejects it instead: the ticket is closed with reason `refund_rejected: <comment>` (or `refund_rejected` with no comment) and nothing is refunded. An unknown ticket returns `404`. A ticket that isn't waiting for an approval returns `409`: it was already approved or rejected, it is not a refund, its refund broke a rule, it is still being decided, or it has finished.

### Fake model

The fake model (`src/agentic_ticket_workflow/fake_llm.py`) is simple and rule-based. It goes through the same tool loop and returns messages in the same shape as a real model. First it calls `get_customer`, then `get_invoices` if the rule needs invoices, then `search_kb`. The search query is the ticket's subject and body plus the customer's status (e.g. `suspended`). The first rule with a keyword in the subject or body decides:

| Keywords | Category / priority | Action |
| --- | --- | --- |
| `password`, `log in`, `login` | account / normal | reply with the top KB article |
| `outage`, `errors`, `down` | technical / urgent | escalate (`possible_outage`) |
| `locked`, `suspended` | account / high | reply with the top KB article (looks up invoices first) |
| `pizza`, `lunch`, `restaurant` | other / low | close (`not_support_request`) |
| `refund`, `charged twice` | billing / normal | refund the latest invoice, using an amount stated in the ticket if any (looks up invoices first) |

A ticket that matches no rule escalates with `no_matching_rule`, a reply rule with no KB hit escalates with `no_kb_article`, and a refund rule for a customer with no invoices escalates with `no_invoice`, so a person sees it. The refund rule is deliberately naive: it believes an amount written in the ticket, as a model following injected instructions would, so T-6 proposes 5000 EUR and the decision rules below have something to stop. Limits: keywords are case-insensitive substring matches (`down` also matches `download`), and the rules were written with the example tickets in mind. It is a stand-in for running with no key, not a classifier.

### Decision rules

Every decision is checked in plain Python (`src/agentic_ticket_workflow/rules.py`) before anything is acted on. A decision that breaks a rule is not carried out. The ticket is escalated instead, with the broken rule's code as the reason, and the code is shown as `violation` in `GET /tickets/{id}`. The ticket text is never trusted: whatever it tells the model, the rules run in code on the model's output.

| Code | Broken rule |
| --- | --- |
| `category_not_allowed` | category is not one of `account`, `billing`, `technical`, `other` |
| `priority_not_allowed` | priority is not one of `low`, `normal`, `high`, `urgent` |
| `action_not_allowed` | action is not one of `reply`, `refund`, `escalate`, `close` |
| `refund_invoice_not_found` | the refunded invoice doesn't exist |
| `refund_invoice_of_other_customer` | the refunded invoice belongs to another customer |
| `refund_amount_not_positive` | the refund amount is not above 0 |
| `refund_amount_above_invoice` | the refund amount is above the invoice amount |

- **Allowed values** are named from the typed decision's parse errors, so the `Decision` schema stays the only list of them. `decide` is not retried for them, because asking again doesn't make an answer allowed. Other unreadable answers are not named this way.
- **Refund rules** run after the model, in their own `check` step (an activity, so the workflow stays deterministic). They read the invoices from the data files, never from the model's tool results. A proposed amount of NaN or infinity is kept and stopped like any other; JSON shows it as the string `"nan"` or `"inf"`.
- A refund that passes every rule waits at `awaiting_approval` for `POST /tickets/{id}/approval` (see [Approve a refund](#approve-a-refund)). Approve issues exactly that refund, once, even when the helpdesk fails and `act` is retried (the retry reuses the idempotency key `ticket-<id>:refund`). Reject closes the ticket with `refund_rejected[: comment]`. The approval is a Temporal Update whose validator refuses any answer the ticket isn't waiting for, so a second or late answer never reaches the workflow. For now the wait has no time limit; the 24 h timeout comes with S-06.
- Limits: a refund of an unpaid invoice passes the rules, and so does a refund of the same invoice in full from two tickets. The person who decides on the refund is the only guard there.

## Tests

```sh
uv run pytest
```

The tests need no network and no API key. The workflow and API tests use Temporal's time-skipping test server. The first run downloads that server once and caches it in the system temp folder, so later runs work offline.

Lint and format checks use [Ruff](https://docs.astral.sh/ruff/) (configured in `pyproject.toml`):

```sh
uv run ruff check          # lint (add --fix to apply safe fixes)
uv run ruff format --check # formatting (drop --check to reformat)
```

## Known limitations

- **Duplicate detection lasts only as long as Temporal's retention period.** A resubmitted ticket ID returns the existing processing only while Temporal keeps that workflow. The `default` namespace keeps it for **24 h** after it closes. After that, the same ID starts a new workflow. Then only the fake helpdesk's idempotency keys stop the action from being repeated.
- **The fake helpdesk keeps its idempotency keys in memory, per worker process.** They are lost when the worker restarts. They are also not shared between workers, so run exactly one worker. A second worker on the same task queue (e.g. one started with `uv run` beside compose) could perform a retried action again.
- The API has no auth. Anyone who can reach it can approve a refund, and the `approver` name is whatever the caller sends. It is logged unverified, as an audit trail.
- The approval comment is free text, so it is kept only in the ticket status (`approval` in `GET /tickets/{id}`, stored in Temporal history), never in the logs.

## Azure deployment

> **Not deployed.** This section describes how the service would run on Azure Container Apps (ACA). Nothing in this repo creates Azure resources.

### Services

One ACA environment in **Sweden Central**, linked to a Log Analytics workspace:

| Component | Azure service | Notes |
|---|---|---|
| `api` | Container App | External HTTP ingress, port 8000. Same image as the worker. |
| `worker` | Container App | No ingress, 1 replica, single-revision mode. Command: `python -m agentic_ticket_workflow.worker`. |
| `temporal` | Container App (`temporalio/server`) | Internal TCP ingress on 7233, 1 replica, single-revision mode. |
| `temporal-ui` | Container App (`temporalio/ui`) | Internal ingress only, never public: the UI has no auth and can signal, cancel or terminate workflows. Approvals are Temporal Updates sent by the API, not signals. |
| `temporal-schema` | Container Apps Job (`temporalio/admin-tools`) | Run manually to create or upgrade the schema **before** the server starts (ACA has no `depends_on`). |
| Temporal persistence | PostgreSQL Flexible Server (Burstable B1ms) | |
| LLM | Azure OpenAI | Set `LLM_MODE`, `LLM_BASE_URL` and `LLM_MODEL` to use it. |
| Images | Azure Container Registry (Basic) | `temporalio/*` images pinned to one fixed version, never `latest`. |

Locally, `docker-compose.yml` runs the single-container Temporal dev server (`temporal server start-dev`, SQLite). In Azure, the production server runs on PostgreSQL with a separate UI and schema job.

**Alternative:** use Temporal Cloud instead. The API and worker then connect over TLS with an API key from Key Vault. That removes `temporal`, `temporal-ui`, `temporal-schema` and PostgreSQL, but Temporal then runs outside Azure.

### Secrets

- Secrets live in **Key Vault**: `LLM_API_KEY` and the PostgreSQL password.
- Container apps reference them as Key Vault secrets through a **user-assigned managed identity** that has only the `Key Vault Secrets User` role.
- The deploy identity gets no Key Vault data roles.
- Other settings are plain env vars with the same names as in `.env.example`.
- The repo holds no secrets.

### Scaling

- **`api`:** stateless, so it scales on HTTP concurrency (for example 1–3 replicas).
- **`worker`:** fixed at 1 replica in single-revision mode.
  - Single-revision mode means an old and a new worker never poll the same task queue at once. Otherwise a refund paused in its 24 h approval wait could resume on different code and fail replay.
  - More replicas would be the next step. Temporal spreads work across workers on the same task queue.
- **`temporal`:** 1 replica, no high availability.

### What to watch

The API and worker write JSON log lines with `ticket_id` and `workflow_id`, and never the ticket body. To find every log line for one ticket in Log Analytics:

```kusto
ContainerAppConsoleLogs_CL
| where ContainerAppName_s in ("api", "worker")
| where Log_s has "T-6"
| project TimeGenerated, ContainerAppName_s, Log_s
| order by TimeGenerated asc
```

Each line is one JSON object (locally: `docker compose logs api worker | grep T-1`):

```json
{"ts": "2026-11-07T07:33:39.832+00:00", "level": "INFO", "logger": "agentic_ticket_workflow.workflow", "message": "decision made", "ticket_id": "T-1", "workflow_id": "ticket-T-1", "run_id": "…", "attempt": 1, "category": "account", "priority": "normal", "action": "reply", "tools": ["get_customer", "search_kb"]}
```

- **Fields:**
  - Always: `ts`, `level`, `logger` and `message`.
  - On ticket lines: `ticket_id`, `workflow_id`, and from Temporal `run_id`, `attempt` and `activity_type`.
  - Allow-listed values: `step`, `status`, `category`, `priority`, `action` (type only), `tools` (names only), `reason_code` (code-produced codes only), `helpdesk_ref`, `error_type`, and for approvals `approved` and `approver`.
  - A failure (such as a helpdesk retry) logs `error_type` and `stack` frames, never the exception message.
- **Never logged:** ticket subject and body, model-written text (reply message, reasons, tool arguments), or the approval comment. Any other extra field is dropped by the formatter (`src/agentic_ticket_workflow/logs.py`).
- **`LOG_LEVEL`** sets only the app's own loggers. Temporal and uvicorn stay at `INFO` or above, because Temporal's DEBUG lines dump activity payloads, which contain ticket text.

Alerts:

- **Failed tickets:** a log alert on worker lines that contain `helpdesk_unavailable` or a failed ticket status.
- **Worker down:** metric alerts on the `worker` app, for a restart count above 0 or a replica count below 1.

### Limitations

- Nothing is deployed, and no IaC is included.
- There is no auth on the API, including the approval endpoint.
- ACA internal TCP ingress for Temporal gRPC is untested.
- PostgreSQL may need `btree_gin` allow-listed for Temporal's visibility schema. This is unverified.
- Opening `temporal-ui` in a browser needs VNet access (VPN or a jump host).
