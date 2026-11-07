<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Prompt Injection Escalated by the Rules

- **Plan**: context/changes/injection-escalated/plan.md
- **Scope**: Phases 1 and 2 of 2; all 14 Progress items marked complete
- **Date**: 2026-11-07
- **Verdict**: APPROVED (was NEEDS ATTENTION; F1 fixed in 6e6e277)
- **Findings**: 0 critical, 1 warning (fixed), 0 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS after fix — FAIL at review: the planned NaN escalation was blocked by payload serialization (F1) |
| Scope Discipline | PASS |
| Safety & Quality | PASS after fix — WARNING at review: the required escalation could be lost (F1) |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS — listed automated commands and manual examples pass |

## Findings

### F1 — NaN refund proposals cannot reach the check activity

- **Severity**: WARNING — FIXED in 6e6e277
- **Impact**: MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Adherence / Safety & Quality
- **Location**: src/agentic_ticket_workflow/activities.py:40; src/agentic_ticket_workflow/workflow.py:80; src/agentic_ticket_workflow/models.py:34
- **Detail**: The plan explicitly requires a NaN refund amount to become `refund_amount_not_positive`. `Decision.model_validate_json` accepts NaN, and the direct rule test at `tests/test_rules.py:77` correctly rejects it. However, returning that `DecideResult` from `decide` crosses the configured Temporal Pydantic converter. It serializes the amount as JSON `null`; decoding the activity result as `DecideResult` raises `ValidationError` before `checking` runs. The workflow therefore cannot record the planned violation and escalation on this path. No unchecked refund is issued, but the required final outcome is missing. The existing unit test does not exercise this serialization boundary.
- **Fix**: Preserve non-finite proposals with a JSON-safe representation across activity results, check requests, workflow results, and API responses, and add a regression through the real activities and configured converter. A focused candidate is Pydantic `ser_json_inf_nan="strings"` on `RefundAction`, which represents NaN as the JSON string `"NaN"` while retaining its numeric meaning on parsing. Verify that representation at every boundary and assert the resulting `refund_amount_not_positive` escalation.
  - **Strength**: Keeps the rule in `rules.py`, the model proposal visible, and the planned workflow gate intact.
  - **Tradeoff**: Non-finite amounts need an explicit public serialization representation; a config-only fix without workflow/API coverage could leave another boundary broken.
  - **Confidence**: HIGH — both reviewers and the primary reviewer reproduced the converter failure; the candidate configuration round-trip was checked by the safety reviewer.
  - **Blind spot**: The primary review reproduced the exact converter failure rather than running a deliberately stranded workflow. The candidate fix has not been implemented or validated through the API.
- **Decision**: ACCEPTED — fixed with a different mechanism. `ser_json_inf_nan` on `RefundAction` was tried and does not work: Pydantic applies that config only on the outermost model being serialized, so a nested `RefundAction` still became `null`. Instead `amount_eur` has a field-level JSON serializer that writes non-finite values as `"nan"` / `"inf"` / `"-inf"`, which lax float parsing reads back. This also covers infinity, which had the same defect. Without the fix the workflow did not merely miss the escalation: the activity-result decode failed the workflow task on every retry, so the ticket hung (regression test timed out). The new `test_non_finite_refund_crosses_temporal_and_is_escalated` (NaN → `refund_amount_not_positive`, inf → `refund_amount_above_invoice`) runs through the real converter and `check`. The API returns the proposal as `"amount_eur": "nan"`.

## Scope and evidence

Reviewed `241ae3d..229127c`: implementation commits `5e00ef7` (Phase 1) and `4ba47af` (Phase 2), closeout `dfd0501`, and roadmap metadata `229127c`. The working tree was clean before review. Command-scoped Git `safe.directory` was used because the execution account differs from the repository owner; no global Git configuration was changed.

Two independent reviewers checked plan drift and safety/pattern compliance. Both identified F1. The remaining planned contracts match the implementation:

- Seven fixed violation codes, allowed-value precedence, authoritative invoice lookup, ownership checks, and the bounded amount rule are implemented in plain Python.
- Disallowed values use a sanitized exception and non-retryable activity mapping. Unknown-customer handling retains its separate behavior.
- Serializable decisions enter `checking`; violations are stored before acting, preserve the original decision, and replace the performed action with escalation. Valid refunds retain the planned `refund_needs_approval` hold.
- Production and test workers register `check`. Workflow tests cover both violation paths and the real T-6/T-2 activity chain.
- The fake refund rule is last, requests invoices, chooses the latest invoice, accepts a stated amount, and escalates when there is no invoice.
- README additions document the fake's limitations, seven codes, activity sequence, and accepted limitations. Change and roadmap files are lifecycle metadata, not unexplained product expansion.

Approval waits, other unreadable-answer/LLM failure mappings, workflow versioning, and broader deployment work remain explicitly outside this slice. This verdict concerns S-04 rather than completion of the entire PRD.

## Automated verification

Commands ran against the reviewed working tree on Python 3.14.8. The import-boundary command initially encountered a sandbox denial on uv's cache lock; its approved rerun passed. Shared full-suite and Ruff criteria were verified once against the final implementation.

| Command | Result | Output summary |
|---------|--------|----------------|
| `uv run pytest tests/test_rules.py` | PASS | 23 passed in 0.08 s |
| `uv run pytest tests/test_agent.py tests/test_workflow.py tests/test_api.py tests/test_logs.py` | PASS | 51 passed in 12.49 s |
| `uv run pytest tests/test_agent.py` | PASS | 19 passed in 0.07 s |
| `uv run pytest tests/test_workflow.py` | PASS | 19 passed in 9.40 s |
| `uv run pytest` | PASS | 86 passed in 11.83 s |
| Plan's AST check of `rules.py` imports | PASS | Imports only typing, pydantic, and agentic_ticket_workflow.models |
| `uv run ruff check` | PASS | All checks passed |
| `uv run ruff format --check` | PASS | 58 files already formatted |

The additional read-only F1 probe used the installed `PydanticPayloadConverter`, the same converter class configured by `pydantic_data_converter`:

```text
Local rule: refund_amount_not_positive
Payload: {"decision":{"category":"billing","priority":"normal","action":{"type":"refund","invoice_id":"INV-1002","amount_eur":null}},"tool_calls":[]}
Decode failure: 1 validation error for DecideResult
decision.action.refund.amount_eur
  Input should be a valid number [type=float_type, input_value=None, input_type=NoneType]
```

## Manual verification evidence

All checked manual items have direct evidence from the preceding verification turns in this same session. They were not inferred from checkmarks alone or repeated by rebuilding during this review.

- **1.6**: Built a fresh `atw-s04` project with a temporary Compose override mapping the API to 18000, Temporal gRPC to 17233, and the UI to 18233. T-1 POST returned 202 with `created=true`; GET completed with `received, deciding, checking, acting, done` and `violation=null`. A headless Chrome render of the UI showed scheduled activity events 5 (`decide`), 11 (`check`), and 17 (`act`). The screenshot and rendered DOM were inspected.
- **2.5**: Rebuilt that isolated project after Phase 2. Newly submitted T-6 completed with the retained INV-1002 proposal for 5000.0, violation `refund_amount_above_invoice`, and an escalation result with the same reason.
- **2.6**: Newly submitted T-2 completed with INV-1002 for 49.0, `violation=null`, and escalation reason `refund_needs_approval`.
- **2.7**: Parsed the isolated worker's JSON logs. T-6 entries had `ticket_id=T-6` and `workflow_id=ticket-T-6`; rule-check and rule-broken entries carried `reason_code=refund_amount_above_invoice`. The entire captured worker log contained neither `5000` nor the injection text. Both tickets' performed-action logs showed escalation. T-6's proposed action type `refund` appeared in the decision log as intended; it was never the performed action. Temporal history independently showed exactly one scheduled `act` per ticket, each with an escalation input and the expected reason.
- **2.8**: `down -v` with the explicit `atw-s04` project and alternate-port override removed the three test containers, network, and only `atw-s04_temporal-data`. Compose subsequently showed no `atw-s04` containers; the pre-existing `agentic-ticket-workflow` and `mail-triage-agent` stacks remained running.

Local verification artifacts, outside the repository: `%TEMP%/atw-s04-temporal-ui.png`, `%TEMP%/atw-s04-ui.html`, and `%TEMP%/atw-s04-phase2-worker.log`. Temporal test history was removed as explicitly requested.

## Review state

Only this report and the change's review-status stamp were written by this review. Progress and roadmap were left unchanged. The review itself applied no application fixes. F1 was then triaged as accepted and FIXED in 6e6e277 (see its Decision).
