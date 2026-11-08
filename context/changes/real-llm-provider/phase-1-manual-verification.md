# Phase 1 manual verification

Date: 2026-11-08. Executed against the local Docker Compose stack at the user's request. Both checks passed. No live LLM request or API key was used.

## 1.6 — Fake-mode Compose regression: PASS

- Ran `docker compose up --build -d` with process-local fake-mode overrides and empty provider settings.
- Used T-1's actual customer, subject and body from `src/agentic_ticket_workflow/data/tickets.json`, changing only its ID to `S08-P1-20261108-194010-T1`. The customer is `C-200`.
- `POST /tickets` returned HTTP 202 with `created: true` and workflow ID `ticket-S08-P1-20261108-194010-T1`.
- Polling `GET /tickets/S08-P1-20261108-194010-T1` reached `status: completed`, `step: done`, category `account`, priority `normal`, action `reply`, article IDs `["KB-1"]`, and Helpdesk reference `HD-1`.
- Worker startup at `2026-11-08T18:39:41.533+00:00` logged `worker started on task queue tickets, LLM mode fake`.
- The `model decided` record identified `get_customer` and `search_kb`. The Helpdesk action succeeded on attempt 3 after two temporary failures; the workflow finished at `2026-11-08T18:40:14.438+00:00`.

## 1.7 — Invalid worker configuration, independent API: PASS

Used a temporary Compose override at `%TEMP%/atw-s08-bad-llm.yaml` to set the following on both API and worker. Explicit empty YAML values avoid accidental fallback to settings from a local `.env`.

```yaml
LLM_MODE: openai
LLM_BASE_URL: http://example.invalid/v1
LLM_MODEL: ""
LLM_API_KEY: ""
```

- Ran `docker compose -f docker-compose.yml -f "$env:TEMP/atw-s08-bad-llm.yaml" up -d`.
- The worker failed at `LlmSettings.from_env()` before connecting to Temporal, reporting `ValueError: LLM_MODEL must be set when LLM_MODE=openai`. Repeated startup failures were visible under the existing restart policy.
- The API remained running. `GET /tickets/S08-NO-SUCH-TICKET` returned HTTP 404 while the bad settings were active.
- No provider call was needed: validation failed before model construction.

## Restored state

Restored the base Compose configuration with process-local fake-mode overrides using `docker compose up --build -d`. Temporal, API and worker were all running afterward. The worker logged `LLM mode fake` at `2026-11-08T18:42:35.050+00:00`. The earlier verification ticket remained readable as a completed reply citing KB-1.

No repository `.env`, application code or existing Temporal volume was changed. Phase 2 live-provider verification remains for the user. No commit was made.
