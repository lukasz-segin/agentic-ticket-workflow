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

A refund is never issued without a person. Submit T-2 (a double charge), and it stops at `awaiting_approval` with the proposed refund in `decision` and the end of the wait in `approval_deadline` (24 h after it started waiting):

```sh
curl -X POST localhost:8000/tickets -H 'content-type: application/json' --data-binary @- <<'EOF'
{"ticket_id": "T-2", "customer_id": "C-100", "subject": "Charged twice",
 "body": "We were charged twice for September. Please refund the extra payment."}
EOF
curl localhost:8000/tickets/T-2
# {"status":"running","step":"awaiting_approval","decision":{...,"action":{"type":"refund",
#  "invoice_id":"INV-1002","amount_eur":49.0}},"approval_deadline":"2026-11-08T22:41:27.727674Z",
#  "result":null,...}
```

Approve it (`approver` and `comment` are optional). The API answers `200` as soon as the answer is recorded, and the workflow then issues the refund:

```sh
curl -X POST localhost:8000/tickets/T-2/approval -H 'content-type: application/json' \
  -d '{"approved": true, "approver": "Ann", "comment": "duplicate confirmed"}'
# {"ticket_id":"T-2","workflow_id":"ticket-T-2","approved":true}
```

`{"approved": false, ...}` rejects it instead: the ticket is closed with reason `refund_rejected: <comment>` (or `refund_rejected` with no comment) and nothing is refunded. With no answer by `approval_deadline`, the ticket is escalated with reason `approval_timeout` and nothing is refunded. An unknown ticket returns `404`. A ticket that isn't waiting for an approval returns `409`: it was already approved or rejected, its 24 h approval wait ran out, it is not a refund, its refund broke a rule, it is still being decided, or it has finished.

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

### Real model

`LLM_MODE=openai` sends the same tool loop to any OpenAI-compatible Chat Completions endpoint (`src/agentic_ticket_workflow/openai_llm.py`). Three settings choose it:

| Provider | `LLM_BASE_URL` | `LLM_MODEL` | `LLM_API_KEY` |
| --- | --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | a model with tool calling and JSON mode, e.g. `gpt-4.1-mini` (used for the smoke run) | your key |
| Azure OpenAI | `https://<resource>.openai.azure.com/openai/v1/` | the deployment name | the resource key |
| Ollama on the host | `http://host.docker.internal:11434/v1` | e.g. `llama3.1` | empty |

Put them in a `.env` (compose reads it; it is gitignored) or set them for one run:

```sh
LLM_MODE=openai LLM_BASE_URL=https://api.openai.com/v1 LLM_MODEL=gpt-4.1-mini LLM_API_KEY=sk-... \
  docker compose up --build
```

- The worker checks these settings at startup. In `openai` mode an empty `LLM_BASE_URL` or `LLM_MODEL`, or a mode other than `fake` or `openai`, stops the worker with an error naming the setting (the key is never printed). The API doesn't read them, so it keeps serving either way. The worker log's first line names the mode: `worker started on task queue tickets, LLM mode openai`.
- Every call asks for JSON (`response_format: json_object`), and the answer is still parsed strictly as a `Decision`, so the same rules check it. The model must support tool calling and JSON mode.
- Each call has a 20 s timeout and no SDK retries: Temporal's `decide` retry policy is the only retry (see below). One `decide` makes at most 6 model calls (the step limit).
- A provider error, a malformed response body or an unusable answer never puts provider or model text in the logs or in Temporal history. The log carries the reason code and, for a provider error, the error type, e.g. `"error_type": "AuthenticationError"`.
- The decisions can differ from the fake model's expected outcomes for T-1…T-7. The rule checks and the refund approval still bound whatever the model decides.

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
- A refund that passes every rule waits at `awaiting_approval` for `POST /tickets/{id}/approval` (see [Approve a refund](#approve-a-refund)). Approve issues exactly that refund, once, even when the helpdesk fails and `act` is retried (the retry reuses the idempotency key `ticket-<id>:refund`). Reject closes the ticket with `refund_rejected[: comment]`. The approval is a Temporal Update whose validator refuses any answer the ticket isn't waiting for, so a second or late answer never reaches the workflow.
- The wait lasts at most 24 h from entering `awaiting_approval`. It is a durable Temporal timer, so the deadline survives worker restarts. With no answer by then, the ticket is escalated with `approval_timeout`. An answer counts only if the workflow processes it before the deadline. The validator also checks the deadline itself, so an approval queued while the worker was down and delivered after the deadline gets `409`, even though Temporal runs it before the overdue timer. An approval accepted before the deadline is always honoured.
- Limits: a refund of an unpaid invoice passes the rules, and so does a refund of the same invoice in full from two tickets. The person who decides on the refund is the only guard there.

### Errors a retry can't fix

Some tickets can't be decided at all. Those tickets are escalated with a reason code instead of being retried forever, so a person always sees them. In `GET /tickets/{id}` they show `"decision": null` and `result.action` `{"type": "escalate", "reason": "<code>"}`.

| Code | When |
| --- | --- |
| `unknown_customer` | the ticket's customer doesn't exist (T-7). Checked in code before the model is called, so `decide` is not retried. |
| `unreadable_model_answer` | the model's answer is still unusable after 3 `decide` attempts: it doesn't parse as a decision, a tool call is malformed, or no decision comes within the 6-step tool loop. |
| `llm_unavailable` | the model provider is still failing after 3 `decide` attempts (unreachable, timed out, rate-limited or a server error), or the last attempt hit the 60 s `decide` timeout. A request the provider rejects (bad key, unknown model, other 4xx) escalates after one attempt, since a retry fails the same way. |

`decide` is retried up to 3 times in all, with backoff (1 s, then 2 s), because a model may answer properly, or a provider may recover, on the next try. The limit is fixed in code (`DECIDE_RETRY` in `workflow.py`). Any other `decide` error, such as a bug in the code, still fails the ticket. The fake model can't fail, so in the fake-mode compose demo these escalations appear only in the tests (`tests/test_workflow.py`). A real provider can: a wrong `LLM_API_KEY` shows `llm_unavailable` on the next ticket.

### Failed tickets

The helpdesk action (`act`) is retried up to 5 times in all, with backoff (1 s, 2 s, 4 s, 8 s; capped at 10 s, `ACT_RETRY` in `workflow.py`). Every retry reuses the idempotency key `ticket-<id>:<action>`, so a retry never repeats an action. If the action still hasn't gone through after the last attempt, or fails in any other way, the ticket **fails** with reason `helpdesk_unavailable`. It is not escalated, because the escalation itself would need the same helpdesk (FR-007). The workflow fails with error type `helpdesk_unavailable` in the Temporal UI, and the worker logs one `WARNING` line `"ticket failed"` with `"reason_code": "helpdesk_unavailable"`. `GET /tickets/{id}` shows:

```json
{"status": "failed", "step": "failed", "failure_reason": "helpdesk_unavailable", "result": null, ...}
```

The decision stays visible. `helpdesk_unavailable` means the helpdesk never *confirmed* the action. A call can fail after the helpdesk has already carried the action out, so the action may have happened, but never twice. Reading a failed ticket needs a running worker, as reading a running one does.

To see it, make every helpdesk call fail and submit a ticket under a new ID. A reused ID returns the earlier execution.

```sh
HELPDESK_FAILURE_RATE=1.0 docker compose up --build
curl -X POST localhost:8000/tickets -H 'content-type: application/json' \
  -d '{"ticket_id": "FAIL-1", "customer_id": "C-200", "subject": "Forgot password", "body": "I cannot log in."}'
# about 15 s later:
curl localhost:8000/tickets/FAIL-1
```

Ticket state lives in Temporal, so a worker restart in the middle of processing loses no ticket: the new worker picks the workflow up where it was, and retries an interrupted action under the same key (tested in `test_worker_restart_mid_action_performs_it_exactly_once`). That holds only while the fake helpdesk keeps its memory; see [Known limitations](#known-limitations).

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
- **The fake helpdesk keeps its idempotency keys in memory, per worker process.** They are lost when the worker process restarts, so an action interrupted by that restart (recorded, but its result never reported) is performed again by the retry. A real helpdesk would keep the keys on its side. They are also not shared between workers, so run exactly one worker. A second worker on the same task queue (e.g. one started with `uv run` beside compose) could perform a retried action again.
- The API has no auth. Anyone who can reach it can approve a refund, and the `approver` name is whatever the caller sends. It is logged unverified, as an audit trail.
- The approval comment is free text, so it is kept only in the ticket status (`approval` in `GET /tickets/{id}`, stored in Temporal history), never in the logs.
- The approval deadline is fixed at 24 h; it is not configurable.
- **With a real model, the provider sees the ticket text** and the customer, invoice and KB data the tools return. Its decisions are not reproducible; the rule checks and the approval step are what bound them.
- **A `decide` timeout doesn't stop the model calls already under way.** The tool loop runs in a worker thread, and Temporal's 60 s timeout abandons the attempt without stopping that thread. The thread can go on for up to its 6 model calls (20 s each at most) while the retry runs, or after the ticket has escalated. Its result is discarded, so no action comes of it, but the provider usage and the worker's shutdown time can exceed the attempt.
- **Workflow code changes are not versioned.** Adding the approval timer changed the workflow in a way Temporal can't replay for workflows started under older code. A refund already waiting in a local dev server from before the change may fail replay after an upgrade. Reset with `docker compose down -v`, then `docker compose up --build`. This **deletes all local ticket histories** (the `temporal-data` volume); a plain `docker compose down` keeps them.

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
