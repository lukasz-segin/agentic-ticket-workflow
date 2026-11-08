# Phase 2 manual verification

Verified on 2026-11-08 against the rebuilt local Compose stack using real time, the HTTP API, worker logs and the Temporal UI. Checks 2.5, 2.6 and 2.7 all passed. No application code was changed during verification; the automated suite was not rerun.

## Setup

Used the default Compose project, with API at `http://localhost:8000`, Temporal at `localhost:7233` and UI at `http://localhost:8233`. All eight requested ticket IDs returned 404 before submission. Sample contents came from `src/agentic_ticket_workflow/data/tickets.json`; only the IDs were changed.

PowerShell configuration for the failure scenario:

```powershell
$env:HELPDESK_FAILURE_RATE = '1.0'
docker compose --env-file .env.example -f docker-compose.yml up --build -d
```

The example environment file explicitly selected fake LLM mode without a key. Other existing Compose projects were left running.

## 2.5: Exhausted helpdesk retries

`POST /tickets` with T-1's content as `S07-FAIL-1` returned HTTP 202 with `created: true`.

The status reached failure 17.3 seconds after starting the submission and polling check:

```json
{
  "ticket_id": "S07-FAIL-1",
  "workflow_id": "ticket-S07-FAIL-1",
  "status": "failed",
  "step": "failed",
  "steps": ["received", "deciding", "checking", "acting", "failed"],
  "failure_reason": "helpdesk_unavailable",
  "result": null
}
```

The decision remained visible. Run ID: `01a1bc2e-058f-71c4-9833-7f67e9d09cea`.

Downloaded Temporal history and inspected the same execution in the browser UI:

- Event 17 schedules `act`; event 18 starts its final attempt with `attempt: 5`.
- Event 19 reports `RETRY_STATE_MAXIMUM_ATTEMPTS_REACHED`.
- Event 23 fails the workflow with application failure type `helpdesk_unavailable` and `nonRetryable: true`.
- The UI shows FAILED and no pending activities. Its JSON view displays attempt 5 in event 18 and the application failure type in event 23.

Execution URL: <http://localhost:8233/namespaces/default/workflows/ticket-S07-FAIL-1/01a1bc2e-058f-71c4-9833-7f67e9d09cea/history>.

## 2.6: Worker logs

Captured `docker compose logs --no-color --no-log-prefix worker` before restoring the default rate. Exactly one parsed JSON record had `reason_code: helpdesk_unavailable`:

```json
{"ts":"2026-11-08T17:21:51.783+00:00","level":"WARNING","logger":"agentic_ticket_workflow.workflow","message":"ticket failed","ticket_id":"S07-FAIL-1","workflow_id":"ticket-S07-FAIL-1","run_id":"01a1bc2e-058f-71c4-9833-7f67e9d09cea","attempt":1,"action":"reply","reason_code":"helpdesk_unavailable"}
```

Activity failure records show `act` attempts `[1, 2, 3, 4, 5]`. Neither the raw worker log nor the decoded JSON records contain any of the seven sample ticket bodies. Checked the default-rate worker log for those bodies too.

The final activity error was `helpdesk unavailable (known key)`: the fake helpdesk had already recorded the action, but never confirmed it. Workflow failure therefore does not imply that the action never happened.

## 2.7: Default failure rate

Restored the rate and recreated API and worker containers:

```powershell
$env:HELPDESK_FAILURE_RATE = '0.3'
docker compose --env-file .env.example -f docker-compose.yml up -d --no-build api worker
```

Confirmed the worker environment reports `LLM_MODE=fake` and `HELPDESK_FAILURE_RATE=0.3`. Each fresh sample submission returned HTTP 202 with `created: true`.

| Ticket | Status | Step | Outcome |
| --- | --- | --- | --- |
| S07-T-1 | completed | done | Password reset reply, KB-1 |
| S07-T-2 | running | awaiting_approval | Refund INV-1002, 49 EUR; left awaiting approval |
| S07-T-3 | completed | done | Escalation: possible_outage |
| S07-T-4 | completed | done | Suspended account reply, KB-4 |
| S07-T-5 | completed | done | Close: not_support_request |
| S07-T-6 | completed | done | Escalation: refund_amount_above_invoice |
| S07-T-7 | completed | done | Escalation: unknown_customer |

All seven have `failure_reason: null`. Only S07-T-2 remains running, as expected. API, worker and Temporal remain running at the default failure rate after verification.

## Raw evidence

Local evidence is saved under `C:\Users\lukas\AppData\Local\Temp\atw-s07-p2-default-stack-check\`:

- `failure-status.json`, `failure-history.json`, `failure-worker.jsonl`
- `example-statuses.json`, `default-worker.jsonl`, each sample workflow's history
- `temporal-ui-event-18.txt` and `.png`, `temporal-ui-event-23.txt` and `.png`

The temporary driver is `C:\Users\lukas\AppData\Local\Temp\atw-s07-p2-default-stack-check.py`. Raw evidence is local and may be removed by Temp cleanup; this record preserves the results.
