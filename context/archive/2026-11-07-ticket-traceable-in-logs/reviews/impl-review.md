<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Ticket Traceable in Logs

- **Plan**: `context/changes/ticket-traceable-in-logs/plan.md`
- **Scope**: Full Plan (Phase 1 and Phase 2)
- **Date**: 2026-11-07
- **Verdict**: APPROVED
- **Findings**: 0 critical, 2 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — `ticket_id_from("ticket-")` returns empty string instead of `None`

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/agentic_ticket_workflow/workflow.py:36-38
- **Detail**: `ticket_id_from("ticket-")` returns `""` because `"ticket-".startswith("ticket-")` is True and `removeprefix` produces `""`. Empty string is not a valid ticket ID (identifiers require at least 1 character) and was never minted by `workflow_id_for`.
- **Fix**: Return `None` if the stripped ID is an empty string (`return id_ if id_ else None`).
- **Decision**: FIXED — `ticket_id_from` returns `None` for an empty remainder; added `("ticket-", None)` test case.

### F2 — `ALLOWED_EXTRAS` contains `"reason"`, creating leakage risk for model-generated escalation reasons

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/agentic_ticket_workflow/logs.py:28
- **Detail**: In `models.py`, `EscalateAction` and `CloseAction` have a `reason: str` field containing free-form LLM / ticket text. While `logs.py` intends `reason` only for code-produced codes (e.g. `"refund_needs_approval"` in S-02), keeping the generic `"reason"` in `ALLOWED_EXTRAS` creates a latent hazard: future slices logging `action.model_dump()` or `extra={"reason": action.reason}` will leak model text into logs, violating FR-010 and the lesson *"Ticket text hides in derived payloads"*.
- **Fix A ⭐ Recommended**: Rename the allow-listed extra to `"reason_code"` and emit `extra={"reason_code": "refund_needs_approval"}` in `workflow.py`.
  - Strength: Disambiguates code-produced reason codes from model `action.reason` at the schema level; model-produced `reason` fields are dropped automatically by `ALLOWED_EXTRAS`.
  - Tradeoff: Minor rename in `workflow.py` and `logs.py`.
  - Confidence: HIGH — directly aligns with lesson *"Ticket text hides in derived payloads"*.
  - Blind spot: Requires future slices to log `reason_code` rather than `reason`.
- **Fix B**: Keep `"reason"` in `ALLOWED_EXTRAS` but validate against a frozen set of allowed reason codes in `JsonFormatter`.
  - Strength: Preserves the `"reason"` field name in JSON log output.
  - Tradeoff: Requires maintaining an explicit enum or whitelist of allowed reason strings in `logs.py`.
  - Confidence: MEDIUM — requires centralized maintenance of reason codes in `logs.py`.
  - Blind spot: May couple `logs.py` to workflow domain error codes.
- **Decision**: FIXED via Fix A — allow-listed extra renamed to `reason_code` in `logs.py`; `workflow.py` emits `reason_code`; plan line updated.

### F3 — `handle.result()` on completed workflow lacks 503 handling in `get_ticket`

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/agentic_ticket_workflow/api.py:108
- **Detail**: When `description.status == WorkflowExecutionStatus.COMPLETED`, `ticket_status = await handle.result()` is called without wrapping. If Temporal RPC connectivity drops, it raises an unhandled `RPCError` (HTTP 500) rather than HTTP 503 from `_temporal_unavailable`, unlike `handle.describe` and `handle.query`.
- **Fix**: Wrap `await handle.result()` in `try...except RPCError as err` and call `_temporal_unavailable` if `err.status in _UNAVAILABLE`.
- **Decision**: FIXED — `handle.result()` wrapped like `describe()` (5 s rpc_timeout, 503 on unavailable, re-raise otherwise).

### F4 — Non-defensive type assumption for `temporal_workflow` and `temporal_activity` in `JsonFormatter`

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/agentic_ticket_workflow/logs.py:39-40
- **Detail**: `fields.get("temporal_workflow") or {}` assumes the value is a dictionary if truthy. If an invalid type is passed, calling `.get()` will raise `AttributeError`, causing logging to fail and drop the record.
- **Fix**: Use `isinstance(..., dict)` checks before calling `.get()` on Temporal fields.
- **Decision**: FIXED — `_dict_extra` helper returns the extra only if it is a dict, else `{}`.
