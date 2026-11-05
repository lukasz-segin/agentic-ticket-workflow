---
project: agentic-ticket-workflow
researched_at: 2026-11-05
recommended_platform: Azure Container Apps
runner_up: Render
context_type: mvp
tech_stack:
  language: Python 3.14
  framework: FastAPI + Temporal (temporalio Python SDK)
  runtime: Docker containers (API, Temporal worker, Temporal server + Web UI)
---

## Recommendation

**Deploy on Azure Container Apps (ACA)**, in a single region (Sweden Central preferred on price), with:
- Temporal persisted in Azure Database for PostgreSQL Flexible Server;
- secrets in Key Vault;
- logs in Log Analytics;
- the LLM on Azure OpenAI / Azure AI Foundry, or an external provider.

ACA ties Render on the criteria and leads after the interview weights. It scores Pass on CLI, managed runtime, agent-readable docs and deploy API, and Partial on MCP. The interview answers decided it:
- **Familiar platform:** the developer knows AWS / GCP / Azure.
- **Single region.**
- **Co-location preferred:** the secrets, logs, database and LLM all sit on one platform, in one region.
- **The PRD names Azure** as the deployment the README must describe (FR-012). Infrastructure-as-code is an optional extra (FR-015).

The interview's "minimize cost" answer counts against ACA. It is the most expensive viable option. This was accepted because of the next point.

**Scope note (PRD Non-Goals): nothing is actually deployed.** The deliverables are:
- the README's Azure deployment description;
- optionally, Bicep or Terraform that matches it exactly (FR-015).

All cost figures below are estimates for that description, not a running bill.

## Platform Comparison

**Scoring:** Pass = 2, Partial = 1, Fail = 0. CLI-first, Managed and Deploy API are weighted ×3, Docs ×2 and MCP ×1, for a maximum of 26.

Research ran on 2026-11-05 through parallel web research. Every status below was checked that day.

| Platform | CLI-first | Managed/Serverless | Agent-readable docs | Stable deploy API | MCP / Integration | Weighted | Result |
|---|---|---|---|---|---|---|---|
| **Azure Container Apps** | Pass | Pass | Pass | Pass | Partial | **23** | **Recommended** |
| Render | Partial | Pass | Pass | Pass | Pass | 21 | Runner-up |
| Railway | Partial | Pass | Pass | Partial | Partial | 17 | Third |
| Fly.io | Pass | Partial | Pass | Partial | Partial | 17 | Not shortlisted |
| Vercel | Pass | Pass | Pass | Pass | Partial | 23 | **Filtered**: can't host the Temporal server |
| Cloudflare | — | — | — | — | — | — | **Dropped** (hard filter) |
| Netlify | — | — | — | — | — | — | **Dropped** (hard filter) |

### Per-platform notes

**Azure Container Apps**
- **Containers and networking:**
  - Runs any OCI image; `python:3.14-slim` exists.
  - `temporalio` 1.35.0 ships abi3 wheels, so it installs on Python 3.14.
  - Internal TCP ingress lets the API and worker dial `temporal:7233` without a VNet.
  - A worker with no ingress and `--min-replicas 1` stays always on. An app with no ingress and min 0 can never start again.
- **CLI:** core `az containerapp` (GA) covers:
  - `create` and `update --image`;
  - `revision list/activate` and `ingress traffic set` for rollback;
  - `logs show --follow --format json`.

  Two commands block an unattended agent: `up --repo` without `--token` (opens a browser) and interactive `exec`.
- **Docs:** markdown source in the public [MicrosoftDocs/azure-docs](https://github.com/MicrosoftDocs/azure-docs) repo. Microsoft Learn returns markdown with `?accept=text/markdown`. There is no `llms.txt` (404).
- **MCP:** Partial.
  - The Azure MCP Server is GA (v3.0, 2026-10-29). It has `monitor`, `keyvault`, `postgres` and `deploy` tools but no Container Apps namespace.
  - `azure/container-apps-deploy-action@v1` has no published releases.
- Sources: [ingress](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview), [scale](https://learn.microsoft.com/en-us/azure/container-apps/scale-app), [billing](https://learn.microsoft.com/en-us/azure/container-apps/billing), [secrets](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets), [Azure MCP tools](https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/tools/), [retail prices API](https://prices.azure.com/api/retail/prices).

**Render**
- **Service types fit the stack directly:**
  - FastAPI as a web service;
  - Temporal as a private service (any protocol and port, private network only);
  - the worker as a background worker (outbound only).
- **CLI:** non-interactive, with `RENDER_API_KEY`, `-o json` and `deploys create --wait`, which exits non-zero on failure.
- **No CLI rollback:** rollback is dashboard or REST API only, and an API rollback does not turn off autodeploy. CLI-first is therefore Partial.
- **Docs and MCP:** `llms.txt` plus a `.md` version of every docs page. MCP is GA (since 2025-08-21) but cannot delete resources, change scaling, or create image-backed services.
- **Cost:** about $27–58/month. Starter instances are $7 each; Postgres is $6–19. These prices come from a third-party source and need re-checking.
- **Logs:** 7 days on Hobby. Workers have no free tier.
- Sources: [private network](https://render.com/docs/private-network.md), [deploy Temporal](https://render.com/docs/deploy-temporal.md), [CLI](https://render.com/docs/cli-reference.md), [rollbacks](https://render.com/docs/rollbacks.md), [MCP GA](https://render.com/changelog/render-mcp-server-is-now-generally-available).

**Railway**
- **Cheapest option:** about $8–12/month on Hobby (usage-based). A community Temporal template idles at about 410 MB.
- **Networking:** the private network (`*.railway.internal`, WireGuard) carries gRPC.
- **CLI:** `railway up --ci --json` returns deterministic exit codes.
- **Rollback:** dashboard only. Images are kept 72 h on Hobby.
- **Platform:** `llms.txt` and per-page markdown. The MCP server (`mcp.railway.com`) has no status label, so it is treated as **preview**. There is no log drain, and logs are kept 7 days on Hobby.
- **Image:** Railpack defaults to Python 3.13, so use a Dockerfile.
- Sources: [private networking](https://docs.railway.com/networking/private-networking/how-it-works.md), [CLI up](https://docs.railway.com/cli/up.md), [pricing](https://railway.com/pricing), [MCP](https://docs.railway.com/ai/mcp-server.md).

**Fly.io**
- **Networking:** process groups and 6PN private networking carry raw gRPC to 7233. `fly proxy` gives private access to the Temporal UI.
- **Rollback:** there is no rollback command. You redeploy an earlier image with `fly deploy -i <old image>`, which restores the image only; secrets and `fly.toml` changes stay. Old images are not guaranteed to be kept.
- **Postgres:** Managed Postgres costs $38/month or more, which pushes the total to about $50–55. Legacy `fly postgres` is **deprecated** per community posts.
- **Other gaps:** the MCP server is **experimental**, and shared CPUs are throttled after burst credits run out.
- Not shortlisted: it tied Railway on score but costs more.
- Sources: [private networking](https://docs.fly.io/networking/private-networking), [rollback guide](https://fly.io/docs/blueprints/rollback-guide/), [MPG](https://docs.fly.io/mpg), [MCP](https://docs.fly.io/flyctl/mcp-server).

**Vercel**
- **API:** FastAPI runs on the GA Python runtime, including Python 3.14.
- **Worker:** the Temporal worker could run as a **Vercel Daemon** (**public beta**, production only, no inbound traffic).
- **Temporal server:** it cannot run here, because it needs inbound gRPC on 7233. That forces a split with Temporal Cloud or a second host.
- **Plan:** Hobby is non-commercial and its daemon quota runs out after about 17 days.
- Filtered out under the persistent-process requirement.
- Source: [background workers](https://vercel.com/kb/guide/background-workers-on-vercel).

**Cloudflare**
- **Python Workers** (GA 2026-09-21) can't load `temporalio`, which has no Emscripten wheel.
- **Containers** (GA 2026-04-13):
  - start on request and sleep after 10 min by default;
  - have no guaranteed lifetime;
  - accept HTTP-only inbound traffic, so no gRPC on 7233;
  - have ephemeral disk.
- **No native managed Postgres.**
- Dropped by the persistent-process hard filter.
- Sources: [packages](https://developers.cloudflare.com/workers/languages/python/packages/index.md), [containers FAQ](https://developers.cloudflare.com/containers/faq/index.md).

**Netlify**
- No Python Functions runtime: the Lambda-compatibility path is **deprecated**, and deploys using it are rejected from 2027-07-01.
- No containers and no long-lived processes.
- Dropped by both hard filters (runtime and persistent process).
- Source: [lambda compatibility](https://docs.netlify.com/build/functions/lambda-compatibility/).

### Shortlisted Platforms

#### 1. Azure Container Apps (Recommended)

**Why it won:**
- **Full CLI loop** with structured output: deploy, revisions, traffic split and JSON log tailing.
- **Managed runtime:** TLS, KEDA scaling and managed identity.
- **Only candidate with first-party, same-region services** for everything the developer asked to co-locate:
  - Key Vault references for secrets (GA);
  - Log Analytics;
  - PostgreSQL Flexible Server;
  - Azure OpenAI.
- **Matches the PRD's Azure README requirement**, and IaC (Bicep or Terraform) can describe the whole environment.

**Costs it carries:** highest estimated price, Partial MCP coverage, and the Temporal-specific setup work recorded in the risk register.

#### 2. Render

**Strengths:**
- Native service types map one-to-one onto API, worker and Temporal.
- GA MCP server, `llms.txt`, and about half Azure's estimated cost.

**Gaps vs ACA:**
- No CLI rollback.
- No Key Vault-class secret store or log-analytics product.
- No first-party LLM.
- Not the platform the PRD asks the README to describe.

#### 3. Railway

**Strengths:** cheapest by far, plus a ready (community) Temporal template.

**Gaps vs ACA:**
- Dashboard-only rollback.
- Preview MCP.
- 7-day logs with no drain, and single-node Postgres by default.
- Not Azure.

## Temporal hosting: self-hosted vs Temporal Cloud

The default design self-hosts Temporal on ACA: a `temporal` server app, a `temporal-ui` app, and PostgreSQL Flexible Server for persistence.

**Alternative: Temporal Cloud.** The worker and API connect to a Temporal Cloud namespace over TLS, using an API key or mTLS certificate stored in Key Vault. This removes four pieces:
- the Temporal server app;
- the UI app (Temporal Cloud has its own UI);
- the PostgreSQL server;
- the schema-setup job.

It also removes most of the risk register's Temporal-specific rows. The trade-offs:
- **Usage-based price, unverified:** the Essentials tier was historically a $100/month minimum, and trackers report it was replaced in 2026-09 by pay-as-you-go with no base fee.
- **External dependency:** Temporal Cloud is outside Azure, which weakens co-location.

The README should present self-hosted as the primary design and Temporal Cloud as the alternative.

## Anti-Bias Cross-Check: Azure Container Apps

### Devil's Advocate — Weaknesses

1. **The Temporal Web UI needs its own app.** A container app has one main ingress port, so the UI (8080) cannot share the server's TCP ingress on 7233. It runs as a separate **internal-ingress** app (a 4th container app in Azure). The UI has no authentication, so it must never get external ingress without Easy Auth / Entra ID in front. Reaching an internal-only UI from a browser needs VNet access (VPN or jump host). ACA has no `port-forward` command.
2. **The idle discount will not apply.** A replica is billed at the idle rate only below 0.01 vCPU and 1 KB/s. The Temporal server's background work and the worker's long-polling keep both above that threshold. Realistic compute is about $40/month, not the $16 all-idle figure.
3. **Temporal schema bootstrap is manual.** `temporalio/auto-setup` is **deprecated**. Schema creation and updates must run as an ACA Job with `temporalio/admin-tools` before the server starts, and ACA has no `depends_on` ordering. PostgreSQL Flexible Server may need `btree_gin` allow-listed in `azure.extensions` for Temporal's visibility schema (**unverified**).
4. **Compose and ACA configuration drift apart.** `docker-compose.yml` is not the deploy artifact. The same environment variables and settings live in both Compose and the ACA app definitions (or Bicep), and can diverge.
5. **Revision traffic-splitting is unsafe for the worker.** In multiple-revision mode, old and new worker revisions poll the same task queue. A workflow paused in its 24 h refund wait can then resume on different code and fail replay with a non-determinism error.

### Pre-Mortem — How This Could Fail

Six months on, the team had treated Container Apps as "Docker Compose in the cloud". To avoid a fourth app, the first deploy put the Temporal UI on public HTTP ingress. A scanner found it, and anyone could read customer workflows and send approval signals to waiting refunds. After that was locked down, a routine worker update went out in multiple-revision mode "for safe rollback". Old and new workers shared the task queue, three refunds waiting for approval failed replay with non-determinism errors, and their approvals landed on broken workflows. Meanwhile the bill was four times the forecast: the server and worker never reached the idle rate, and the environment sat in West Europe instead of Sweden Central. A rebuild from IaC failed quietly, because the schema job raced the server and `btree_gin` wasn't allow-listed. Nobody noticed: logs flowed into Log Analytics, but no one had written an alert. The root causes were assuming Compose semantics, ignoring Temporal's versioning model during revisions, and taking "scale to idle" pricing at face value for an always-busy server.

### Unknown Unknowns

- **Single-revision mode for the worker.** Run the worker (and the Temporal server) with `--revisions-mode single`. Rollback means redeploying the previous image tag, not shifting traffic. Only the stateless API may use traffic splitting.
- **Easy Auth (built-in authentication) works only on HTTP ingress.** It can protect a UI app, but never the server's gRPC 7233. Keep 7233 internal-only.
- **Prices vary by region.** The active vCPU rate is about $0.000034/s in West Europe vs $0.000024/s in Sweden Central and East US, roughly 40% more. Pick the region on purpose.
- **Key Vault caveats.**
  - Unversioned Key Vault references refresh within 30 minutes and restart the revision.
  - The Container Apps Contributor and Operator roles can call `listSecrets`, so scope roles narrowly.
- **No `llms.txt` on Microsoft Learn.** Agents should fetch docs with `?accept=text/markdown` or read the GitHub source.

**Decision (2026-11-05):** the developer accepted Azure Container Apps with the risks below. They made four corrections:
- the UI runs as a separate internal-ingress app;
- nothing is deployed, so costs are estimates;
- Temporal Cloud is documented as the alternative;
- the `btree_gin` requirement is marked unverified.

## Operational Story

This describes how the environment would operate if deployed. Per the PRD, it is documented, not executed.

- **Preview deploys:** none by default. ACA has no per-PR preview URLs. A preview means deploying a new **API** revision with a revision label (`--revisions-mode multiple`, label `pr-<n>`) at 0% traffic, which gives the label its own URL. Worker and Temporal changes have no preview path; test them in a separate ACA environment.
- **Secrets:**
  - Key Vault holds the LLM API key, the PostgreSQL password and any Temporal Cloud key.
  - Container apps read them as `keyvaultref:` secrets through a user-assigned managed identity with the `Key Vault Secrets User` role.
  - GitHub Actions uses OIDC federated credentials; no stored client secret.
  - Rotation: add a new secret version in Key Vault. Unversioned references pick it up within 30 minutes, with a revision restart.
- **Rollback:**
  - API: `az containerapp ingress traffic set -n api -g <rg> --revision-weight <previous-revision>=100`. Takes about a minute.
  - Worker and Temporal server: `az containerapp update -n worker -g <rg> --image <registry>/worker:<previous-tag>`. Takes a few minutes.
  - Caveats: worker code must stay replay-compatible with in-flight workflows, and Temporal schema updates do not roll back.
- **Approval:**
  - **Human only:** creating or deleting the resource group, environment, PostgreSQL server or Key Vault; rotating or deleting primary secrets; changing role assignments; deploying to production.
  - **Agent, unattended:** read-only queries (`az containerapp show/revision list/logs show`, Log Analytics queries) and deploys to a non-production environment.
- **Logs:**
  - Live: `az containerapp logs show -n <app> -g <rg> --follow --format json --type console`.
  - History: `az monitor log-analytics query -w <workspace-id> --analytics-query "ContainerAppConsoleLogs_CL | where Log_s has '<ticket_id>'"`, or the Azure MCP Server `monitor` tools (GA).
  - The app already emits JSON lines with `ticket_id` and `workflow_id` (FR-010), so they are queryable by ticket.

## Risk Register

| Risk | Source | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Temporal UI exposed publicly without auth (workflow data leak, forged approval signals) | Devil's advocate | M | H | UI runs as a separate **internal-ingress** app. If browser access is needed, use a VNet or VPN, or external ingress **only** behind Easy Auth / Entra ID. Server 7233 is always internal TCP. |
| Worker non-determinism during revision overlap breaks 24 h refund waits | Unknown unknowns | M | H | `--revisions-mode single` for worker and server. Rollback means redeploying the previous image. Use Temporal workflow versioning (`workflow.patched`) for workflow code changes. |
| Real cost exceeds estimate (idle rate never applies; region choice) | Devil's advocate | H | M | Plan on active-rate compute: about $40 compute + $14.5 PostgreSQL B1ms + about $5 ACR (or GHCR, free) + Log Analytics (5 GB free) ≈ **$60–75/month estimate**. Choose Sweden Central. Set an Azure budget alert. Nothing is deployed for the MVP. |
| Schema setup races server start, or a missing `btree_gin` allow-list breaks the visibility schema | Pre-mortem | M | H | Manual ACA Job (`temporalio/admin-tools`, `temporal-sql-tool`) runs and is checked **before** the server app is created. Add `btree_gin` to `azure.extensions` if Temporal's PostgreSQL visibility schema needs it (**unverified**). |
| `temporalio/auto-setup` used in the cloud because Compose uses it | Research finding | M | M | Compose may keep a dev-only image. The README and IaC use `temporalio/server` plus the separate schema job. Note the **deprecated** status in the README. |
| Compose and ACA/IaC configuration drift (env vars, image tags, settings) | Devil's advocate | M | M | One `.env.example` lists every variable. The IaC parameter file mirrors it. The README's Azure section references the same variable names. |
| Missing alerting: failed tickets (`helpdesk_unavailable`) or a crashed worker go unnoticed | Pre-mortem | M | M | The README describes a Log Analytics alert rule on worker restarts or zero replicas, and on log lines with `status=failed` / `helpdesk_unavailable`. |
| Over-broad roles can read secrets (`listSecrets` via Contributor/Operator) | Unknown unknowns | L | H | Separate a deploy identity (scoped to the resource group, no Key Vault data roles) from the runtime managed identity (`Key Vault Secrets User` only). |
| Agent blocked by interactive commands (`az containerapp up --repo` browser auth, `exec`) | Research finding | M | L | Use `create` / `update --image` with a prebuilt image. Never use `up --repo` without `--token`. No `exec` in automated flows. |
| Azure MCP Server has no Container Apps tools; deploy action has no releases | Research finding | H | L | Use the `az` CLI for ACA operations, and the MCP `monitor`/`keyvault`/`postgres` tools (GA) for read-only queries. Pin any GitHub Action by commit SHA. |
| Scope creep: actually deploying conflicts with PRD Non-Goals and the 2026-11-07 deadline | Unknown unknowns | M | M | The deliverable is the README Azure section (FR-012), plus optional Bicep/Terraform (FR-015) only after FR-001–FR-012 pass. No `az ... create` against a real subscription for the MVP. |
| Temporal Cloud pricing assumed (pay-as-you-go change unverified) | Research finding | L | L | Present Temporal Cloud only as an alternative. Re-check temporal.io/pricing before recommending it. |

## Getting Started

These steps produce the documented deployment (README section and optional IaC). They **do not** deploy anything for the MVP.

1. **Write the README "Azure deployment" section** using this layout:
   - **One ACA environment** in Sweden Central, linked to a Log Analytics workspace.
   - **Container apps:**
     - `api`: external HTTP ingress, port 8000.
     - `worker`: no ingress, min/max replicas 1, single-revision mode.
     - `temporal`: internal TCP ingress, port 7233, min replicas 1.
     - `temporal-ui`: internal HTTP ingress, port 8080.
   - **ACA Job `temporal-schema`:** runs `temporalio/admin-tools` manually.
   - **Persistence:** PostgreSQL Flexible Server (Burstable B1ms).
   - **Secrets:** Key Vault, accessed through a user-assigned managed identity.
   - **LLM:** Azure OpenAI deployment, or an external provider.
   - **Images:** ACR Basic or GHCR.
   - **Alternative:** Temporal Cloud.
2. **Pin images that match the stack:**
   - the API/worker image on `python:3.14-slim`, with `uv sync --frozen` (the project uses `uv_build` and a src layout);
   - `temporalio/server`, `temporalio/ui` and `temporalio/admin-tools` at one fixed Temporal version, not `latest`.
3. **Use these CLI commands for the README (and, optionally, as a Bicep cross-check).** Before quoting a flag, confirm it against the installed extension with `az containerapp <cmd> --help`.
   - Setup:

     ```sh
     az extension add --name containerapp --upgrade
     az provider register --namespace Microsoft.App
     az provider register --namespace Microsoft.OperationalInsights
     az containerapp env create -n <env> -g <rg> -l swedencentral
     ```
   - Temporal server, internal TCP ingress:

     ```sh
     az containerapp create -n temporal -g <rg> --environment <env> --image temporalio/server:<ver> \
       --ingress internal --transport tcp --target-port 7233 --exposed-port 7233 \
       --min-replicas 1 --max-replicas 1 --revisions-mode single
     ```
   - Worker, no ingress, always on:

     ```sh
     az containerapp create -n worker -g <rg> --environment <env> --image <registry>/ticket-workflow:<tag> \
       --min-replicas 1 --max-replicas 1 --revisions-mode single
     ```
4. **Optional, FR-015, only after FR-001–FR-012 pass:** write `infra/main.bicep` mirroring exactly the resources in step 1. Validate with `az bicep build` and `az deployment group what-if`. Never run `create` against a real subscription.
5. **Document the operations commands from the Operational Story** in the README's "what to watch in production" part: log queries, alerts and rollback.

## Out of Scope

The following were not evaluated in this research:
- Docker image configuration
- CI/CD pipeline setup
- Production-scale architecture (multi-region, HA, DR)
- An actual Azure deployment (PRD Non-Goal; documentation and optional IaC only)
