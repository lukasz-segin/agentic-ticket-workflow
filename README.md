# agentic-ticket-workflow

## Azure deployment

> **Not deployed.** This section describes how the service would run on Azure Container Apps (ACA). Nothing in this repo creates Azure resources.

### Services

One ACA environment in **Sweden Central**, linked to a Log Analytics workspace:

| Component | Azure service | Notes |
|---|---|---|
| `api` | Container App | External HTTP ingress, port 8000. Same image as the worker. |
| `worker` | Container App | No ingress, 1 replica, single-revision mode. Command: `python -m agentic_ticket_workflow.worker`. |
| `temporal` | Container App (`temporalio/server`) | Internal TCP ingress on 7233, 1 replica, single-revision mode. |
| `temporal-ui` | Container App (`temporalio/ui`) | Internal ingress only, never public: the UI has no auth and can send signals (approvals). |
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

Alerts:

- **Failed tickets:** a log alert on worker lines that contain `helpdesk_unavailable` or a failed ticket status.
- **Worker down:** metric alerts on the `worker` app, for a restart count above 0 or a replica count below 1.

### Limitations

- Nothing is deployed, and no IaC is included.
- There is no auth on the API, including the approval endpoint.
- ACA internal TCP ingress for Temporal gRPC is untested.
- PostgreSQL may need `btree_gin` allow-listed for Temporal's visibility schema. This is unverified.
- Opening `temporal-ui` in a browser needs VNet access (VPN or a jump host).
