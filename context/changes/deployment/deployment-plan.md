# Plan: deployment, minimal definition of done

> Change folder: `context/changes/deployment/` (identity: `change.md`).
> Status legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked (reason given)
> Owner: agent builds, human reviews.

## Scope

- **Nothing is deployed.** This was checked on 2026-11-06 against the original assignment (`docs/`, paraphrased here, not quoted) and against the PRD.
- **What the assignment requires:**
  - a `docker-compose.yml` that starts the Temporal server with its web UI, the API and the worker;
  - `docker compose up` working in fake LLM mode with no API key;
  - a `.env.example` with variable names and no secrets;
  - a README section on how the service *would* be deployed to Azure.
- **Definition of done:** the four phases below.
- **Not in this plan:** Bicep/Terraform, CI, a deploy runbook, a config-drift test, Postgres in compose.

## Deployment state

- **Deployed:** nothing.
- **Secrets configured:** none, in Azure or GitHub.

## Entrypoints (one image, two commands)

- `api`: `uvicorn agentic_ticket_workflow.api:app --host 0.0.0.0 --port 8000`
- `worker`: `python -m agentic_ticket_workflow.worker`

## Phases

### Phase 1 `[x]`: `.env.example` + AGENTS.md
- [x] AGENTS.md container rule replaced: at least Temporal server + UI + API + worker, and no app DB or queue. Done 2026-11-06.
- [x] `.env.example` with the app variables only, and no real secrets. Done 2026-11-06:

  | Variable | Default |
  |---|---|
  | `TEMPORAL_ADDRESS` | `temporal:7233` |
  | `TEMPORAL_NAMESPACE` | `default` |
  | `TEMPORAL_TASK_QUEUE` | `tickets` |
  | `LLM_MODE` | `fake` |
  | `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | empty |
  | `HELPDESK_FAILURE_RATE` | `0.3` |
  | `LOG_LEVEL` | `INFO` |

  These defaults must be identical to the inline defaults in `docker-compose.yml` (Phase 3).

### Phase 2 `[x]`: `Dockerfile` + `.dockerignore`
- [x] Build on `python:3.14-slim` with the uv binary and `uv sync --frozen --no-dev`. Copy `pyproject.toml`, `uv.lock` **and `README.md`** before the sync that installs the project: `pyproject.toml` declares `readme = "README.md"`, and `uv_build` fails without it. Run as a non-root user. The default `CMD` is the api command; compose overrides it for the worker.
- [x] `.dockerignore` excludes `.venv`, `.env`, `docs/`, `context/`, `.git`, `.claude` and `.agents`.
- Done 2026-11-06. Verified: `docker build` passes; container runs as uid 10001 (`app`) on Python 3.14; `fastapi`, `uvicorn` and the package import; `docs/`, `context/` and `.env` are not in the image. uv pinned to `0.13.1` (matches `uv_build>=0.13.1,<0.14`). The package is installed non-editable, so runtime files (e.g. sample data) must live under `src/agentic_ticket_workflow/` or get their own `COPY`.

### Phase 3 `[x]`: `docker-compose.yml` (3 services)
- [x] `temporal`: the Temporal CLI image `temporalio/temporal:1.9.1` (released 2026-09-14; `1.10.0` is too new to pin), running `server start-dev --ip 0.0.0.0 --db-filename /home/temporal/temporal.db`.
  - Server and web UI run in one container, on ports 7233 (gRPC) and 8233 (UI). `--ui-ip` defaults to `--ip`, and `start-dev` creates the `default` namespace itself.
  - A named volume is mounted on `/home/temporal`. Without it, a Temporal restart loses workflows and breaks the restart NFR.
  - Don't use `/data`. The image runs as `temporal` (uid 1000) and has no `/data`, so a volume there would be owned by root and SQLite couldn't write to it. `/home/temporal` exists in the image and belongs to that user, and Docker copies that ownership into a new named volume.
- [x] `api` (port 8000) and `worker`: `build: .`. Every variable has an inline default (`${LLM_MODE:-fake}`, …), so a fresh clone runs with no `.env`.
- The api and worker retry the Temporal connection at startup. That's app-side and covered by the FR-001 work.
- Done 2026-11-06. Verified: `docker compose config` is valid; the api environment matches `.env.example` exactly; `docker compose up -d temporal` gives UI 200 on `localhost:8233` and `cluster health` SERVING; `temporal.db` is written to the volume as `temporal`; a test workflow was still RUNNING after `docker compose restart temporal`; `docker compose build` builds one shared image (`agentic-ticket-workflow:local`). api/worker not started yet: their modules come with FR-001 (Verification step 1).

### Phase 4 `[x]`: README "Azure deployment" section (FR-012, about one page)
Content comes from `context/foundation/infrastructure.md`.
- [x] **Services:**
  - one Container Apps environment in Sweden Central, linked to Log Analytics;
  - `api`: external HTTP;
  - `worker`: no ingress, 1 replica, single revision;
  - `temporal`: `temporalio/server`, internal TCP 7233;
  - `temporal-ui`: internal ingress only, never public (it has no auth);
  - a manual `temporal-schema` job;
  - PostgreSQL Flexible Server for Temporal;
  - Azure OpenAI for the LLM;
  - ACR for images.

  One sentence explains that compose uses the dev server locally, while Azure uses the server + Postgres.
- [x] **Secrets:** Key Vault, read through a user-assigned managed identity (`Key Vault Secrets User`). No secrets in the repo.
- [x] **Scaling:** the API scales on HTTP. The worker is fixed at 1 replica; scaling it is a next step. Temporal runs at 1 replica, with no HA.
- [x] **What to watch:** JSON logs in Log Analytics, queried by `ticket_id` (one KQL example). Alerts on `helpdesk_unavailable` or failed tickets, and on worker restarts or 0 replicas.
- [x] **Limitations:** not deployed; no auth; internal TCP ingress untested.
- Done 2026-11-06. README `## Azure deployment` written (~1 page); covers the FR-012 Azure item (services for API, background processing, workflow engine and LLM; secrets; scaling; what to watch) and answers Verification step 3. Temporal Cloud added as the alternative, per `infrastructure.md`.

## Verification (local)

1. From a clean clone with no `.env`, `docker compose up -d` starts `temporal`, `api` and `worker`, and the UI loads on `localhost:8233`.
   - This needs the app code (`agentic_ticket_workflow.api:app` and `agentic_ticket_workflow.worker`, from the FR-001 work), so it can't run first.
   - Until then, check `docker compose up -d temporal` on its own.
2. Once the app exists, workflows survive `docker compose restart temporal`.
3. The README section answers the four assignment questions: services, secrets, scaling, what to watch.

## Sources
- [S1] ACA ingress (internal TCP): https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview
- [S2] ACA secrets / Key Vault references: https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets
- [S3] Temporal CLI `server start-dev` flags (`--ip`, `--ui-ip`, `--db-filename`, UI port 8233): https://docs.temporal.io/cli/server
- [S4] Temporal CLI image (user `temporal`, uid 1000, no `/data`): https://github.com/temporalio/cli/blob/main/Dockerfile
