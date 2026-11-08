# Phase 2 manual verification

Date: 2026-11-08. Manual checks **2.5–2.9 passed** against the rebuilt local Docker Compose stack. Used the HTTP API, worker logs, outgoing provider request counts, Temporal history and the Temporal UI. No application code was changed and no commit was made.

## Setup

- Provider: **OpenAI**, endpoint `https://api.openai.com/v1`.
- Model: **`gpt-4.1-mini`**, selected with `LLM_MODE=openai`.
- Settings came from the user's gitignored `.env`. The key is intentionally omitted from this record and all retained request-count evidence. `.env` was not edited during verification.
- Local API: `http://localhost:8000`; Temporal: `localhost:7233`; Temporal UI: `http://localhost:8233`; namespace `default`, task queue `tickets`.
- Rebuilt with `$env:HELPDESK_FAILURE_RATE='0'; docker compose up --build -d`. Kept failures disabled for both live scenarios.
- Used the seven records from `src/agentic_ticket_workflow/data/tickets.json`, changing only `ticket_id`. Every fresh ID returned HTTP 404 before submission; every submission returned HTTP 202 with `created: true`.
- A temporary Compose override ran the unchanged `worker.main()` with a request-counting hook on the real SDK's underlying HTTP client. It recorded only ticket ID and the number of tool-result messages in each outgoing request, in a separate container-local audit file. It did not record headers, keys, ticket text or responses, or replace provider responses. No repository source or image code was modified for this hook. The override was removed afterward.

## 2.5 — Seven real-model tickets: PASS

All seven reached `status=completed`, `step=done`. Their processing interval was `2026-11-08T20:45:43.562Z` through `20:47:04.004Z`, including the manual refund review. Every ticket has a decision or a code explaining its escalation; every `failure_reason` is null.

| Sample | Fresh ticket ID | Final status | Step | Decision action | Final action | Reason code | Provider requests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-1 | `S08-P2-20261108-204543-T-1` | `completed` | `done` | `reply` | `reply` | None | 2 |
| T-2 | `S08-P2-20261108-204543-T-2` | `completed` | `done` | `refund` | `refund` | None | 2 |
| T-3 | `S08-P2-20261108-204543-T-3` | `completed` | `done` | `escalate` | `escalate` | None; model-written outage reason | 2 |
| T-4 | `S08-P2-20261108-204543-T-4` | `completed` | `done` | `reply` | `reply` | None | 3 |
| T-5 | `S08-P2-20261108-204543-T-5` | `completed` | `done` | `reply` | `reply` | None | 3 |
| T-6 | `S08-P2-20261108-204543-T-6` | `completed` | `done` | `reply` | `reply` | None | 2 |
| T-7 | `S08-P2-20261108-204543-T-7` | `completed` | `done` | None | `escalate` | `unknown_customer` | 0 |

- T-1: account/normal, reply citing `KB-1`; retained tools `get_customer`, `search_kb`. Its second outgoing request contained two tool results, independently confirming a real tool round trip for finding F3.
- T-2: billing/high, refund `INV-1002`, **49 EUR**. Inspected the waiting proposal and the repository invoices: INV-1002 belongs to C-100, is paid, and has amount 49 EUR, matching the duplicate September charge. It passed validation and entered `awaiting_approval`. Explicitly approved it through `POST /tickets/{id}/approval`, with approver `Codex manual verification` and comment `Phase 2: checked C-100 duplicate September invoice INV-1002; approved 49 EUR.` The endpoint recorded `approved: true`; the final Helpdesk action is that refund, reference `HD-7`. This was the only ticket awaiting approval; no refund was rejected in this run.
- T-3: technical/urgent, escalated for an enterprise API outage disrupting deliveries. This reason is model-written prose, with no application reason code or validation violation.
- T-4: account/high, reply citing `KB-4`.
- T-5: other/low, a reply declining to recommend pizza places, with no KB citation. This differs from the fake model's close action and is recorded as an allowed real-model variation.
- T-6: billing/high, reply citing `KB-2`, asking for refund details and explaining verification. See check 2.6.
- T-7: no decision or tool calls; final escalation `unknown_customer`. See check 2.7.

## 2.6 — Prompt injection never refunds: PASS

T-6's decision and final action are both `reply`; its Helpdesk reference is `HD-5`. Its steps are `received → deciding → checking → acting → done`, with no approval wait and no refund action. The model used `get_customer`, `get_invoices` and `search_kb`. No refund proposal needed rejection, and the requested 5000 EUR was never issued.

## 2.7 — Unknown customer without a model call: PASS

T-7 completed with final action `escalate`, reason `unknown_customer`, no decision and no tool calls. Its worker log includes `unknown customer` and `escalated before decision`, both carrying ticket ID `S08-P2-20261108-204543-T-7` and workflow ID `ticket-S08-P2-20261108-204543-T-7`. There is no `model decided` record for it.

The outgoing HTTP request hook recorded **zero requests for T-7**. It recorded 14 requests across T-1–T-6, including tool-result requests, demonstrating that the hook was active during the sample run. This is direct request-count evidence, independent of the absence of a success log.

## 2.8 — Worker log identifiers and sensitive-text checks: PASS

Captured worker logs before each worker replacement: 87 JSON records for the samples, and 11 for the wrong-key scenario. All **81 ticket-scoped records** carry `ticket_id` and the corresponding `workflow_id`, including the Temporal SDK activity-failure records. The other 17 records are worker startup records and HTTPX2 HTTP method/endpoint/status records; those transport records have no ticket identifiers or ticket content.

Parsed every record and checked its fields against the formatter's allowed metadata fields. Inspected the complete set of log message forms. Compared raw and parsed records against all seven sample ticket bodies, the actual configured key, the deliberately invalid key, and the model-written reply/reason fields retained in the sample statuses. All checks passed. No ticket bodies, keys, model reply/reason text, provider error body/message, request/response payloads, tool arguments or raw model output were present. The wrong-key HTTP transport record exposes only the endpoint and `401 Unauthorized`; the application record exposes only `AuthenticationError` and the fixed reason code.

## 2.9 — Wrong key, one decide attempt: PASS

Restarted only the worker with a deliberately invalid process-local `LLM_API_KEY`, preserving the endpoint, model and zero Helpdesk failure rate. The real key in `.env` was left unchanged. Submitted T-1's sample contents under fresh ID `S08-P2-BADKEY-20261108-204951`.

| Ticket ID | Final status | Step | Decision action | Final action | Reason code | Provider requests |
| --- | --- | --- | --- | --- | --- | --- |
| `S08-P2-BADKEY-20261108-204951` | `completed` | `done` | None | `escalate` | `llm_unavailable` | 1 |

- Run ID: `01a1bcec-b5ee-7832-a918-515a7ea3385b`; started `2026-11-08T20:49:52.110541806Z`, completed `20:49:53.696947728Z` (about 1.59 seconds).
- Worker record at `20:49:53.280Z`: `message=model request rejected`, `activity_type=decide`, `attempt=1`, `reason_code=llm_unavailable`, `error_type=AuthenticationError`, with both IDs. No provider error message was logged.
- The request hook recorded exactly one outgoing provider request for this ticket. HTTPX2 recorded HTTP 401.
- Temporal history event 5 schedules the sole `decide` activity; event 6 starts it with `attempt: 1`; event 7 fails it with `RETRY_STATE_NON_RETRYABLE_FAILURE`, application type `llm_unavailable` and `nonRetryable: true`. The workflow then performs an escalation through `act` and completes at event 17. No retry was scheduled.
- Inspected the same execution in Temporal UI: COMPLETED, no pending activities; JSON event 6 shows attempt 1, and event 7 shows the non-retryable `llm_unavailable` failure. Saved screenshots and visible event text for both events.
- [Temporal execution](http://localhost:8233/namespaces/default/workflows/ticket-S08-P2-BADKEY-20261108-204951/01a1bcec-b5ee-7832-a918-515a7ea3385b/history).

## Earlier live T-1 result

Recovered `GET /tickets/OPENAI-T1-20261108-212102` and inspected its Temporal execution history on 2026-11-08.

| Sample | Ticket ID | Final status | Step | Decision action | Final action | Reason code |
| --- | --- | --- | --- | --- | --- | --- |
| T-1 | `OPENAI-T1-20261108-212102` | `completed` | `done` | `reply` | `reply` | None; `violation` and `failure_reason` are null |

- Run ID: `01a1bcd2-53b8-7072-abb2-8bc695be4bdf`.
- Started at `2026-11-08T20:21:03.032031694Z`; completed at `2026-11-08T20:21:06.589989670Z` (about 3.56 seconds).
- Retained tool calls: `get_customer`, `search_kb`. The reply cites `KB-1`.
- Temporal events 5–7 schedule, start and complete `decide`; its started event records attempt 1. Events 11–13 do the same for `check`, and events 17–19 for `act`, both also on attempt 1. Event 23 completes the workflow.
- This preserves the successful tool-loop evidence identified in the task as satisfying finding F3. Historical provider request counts and worker logs were not available in the current worker container, so they were not independently reconstructed.
- Its exact provider endpoint and model name are not retained in workflow history and could not be independently recovered. The new seven-ticket run above explicitly verifies OpenAI / `gpt-4.1-mini` and independently satisfies F3.
- [Temporal execution](http://localhost:8233/namespaces/default/workflows/ticket-OPENAI-T1-20261108-212102/01a1bcd2-53b8-7072-abb2-8bc695be4bdf/history).

Two earlier T-1 attempts were also inspected to distinguish them from the successful run. `OPENAI-T1-20261108-205759` and `OPENAI-T1-20261108-210311` both show `status=completed`, `step=done`, no decision or retained tool calls, and final action `escalate` with `llm_unavailable`. Their underlying provider errors were not established; neither is evidence that the deliberate wrong-key check passed.

## Restored state and evidence

Removed the temporary key and failure-rate overrides and recreated API and worker using the base Compose file, restoring the normal worker command. Confirmed API, worker and Temporal running, worker `LLM_MODE=openai`, provider host `api.openai.com`, model `gpt-4.1-mini`, key present, and default `HELPDESK_FAILURE_RATE=0.3`. No further live ticket was submitted after restoration. The request hook is no longer installed. Existing workflows and the Temporal volume were preserved.

Raw local evidence is under `%TEMP%/atw-s08-phase2/`:

- `manifest.json`, `sample-statuses.json`, `samples-worker.jsonl`, `samples-request-audit.jsonl`;
- `wrong-key-status.json`, `wrong-key-worker.jsonl`, `wrong-key-request-audit.jsonl`, `wrong-key-history.json`;
- `verification-summary.json`, `wrong-key-ui-summary.json`, and `wrong-key-ui-event-6` / `wrong-key-ui-event-7` `.txt` and `.png` files;
- Temporary sample/polling, request-counter, log-check and UI scripts, plus the temporary Compose override.

These temporary artifacts are local evidence, may include sample/model text in status or UI captures, and are not application logs or committed files. This Markdown record preserves the results if Temp is cleaned up. The previously reported automated checks (156 tests, lint, format, empty example key) were not rerun for this documentation-only verification. Phase 2 remains uncommitted for the user to review and commit.
