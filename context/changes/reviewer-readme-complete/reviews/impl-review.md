<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Reviewer-Ready README

- **Plan**: context/changes/reviewer-readme-complete/plan.md
- **Scope**: Phases 1–2 of 2 (full plan)
- **Date**: 2026-11-08
- **Verdict**: APPROVED
- **Findings**: 0 critical, 2 warnings, 6 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING (minor drifts: F6, F7) |
| Scope Discipline | PASS (the `.env` / `LLM_MODE=fake` note corrects a mismatch found in live verification, which the plan allows) |
| Safety & Quality | WARNING (F1, F2) |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS (no placeholders; 21/21 anchors; only README + context changed; Ruff clean; 156 tests pass; manual 1.4–1.5 and 2.5–2.9 confirmed by the human with Codex) |

## Findings

### F1 — Submit-and-poll script aborts on start-up connection errors

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: README.md:47, README.md:55-58
- **Detail**: The POST loop catches nothing, and the GET loop catches only `HTTPError`. Right after `docker compose up`, the API can restart while Temporal is still starting (`depends_on` doesn't wait for readiness; `api.py:84` connects at start-up). A `URLError` or `ConnectionResetError` then ends the script with a traceback. A POST that gets a 503 (`api.py:113-116`) also aborts.
- **Fix**: Catch `OSError` (the parent of `URLError` and `HTTPError`) in both loops, and retry each POST until the same 60 s deadline.
- **Decision**: FIXED (re-triaged; first SKIPPED) — both loops catch `OSError`, and each POST is retried until a single 60 s deadline that covers submitting and polling. A retried POST is safe: the workflow ID makes a repeat return `created: false`. Follow-up (raised by Codex): each `urlopen` now gets the time left as its timeout, so a stalled request can't overrun the 60 s. Verified: against a server that accepts but never answers, the script exits after 60.5 s with `TimeoutError`. A cold start runs clean. A second run on the same stack returns `200 already submitted` with unchanged outcomes, and the helpdesk count stays at 6. The 4 "error" lines in the API log are `INFO` lines from the `uvicorn.error` logger. The one worker `WARNING` is T-7's non-retryable `unknown_customer` from `decide`, as expected.

### F2 — Poll loop waits the full 60 s on a ticket that failed before `acting`

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: README.md:59
- **Detail**: Some failures leave `step` at `checking` or `deciding`, with Temporal `status` `failed`: a `check` that runs out of attempts, or an unlisted `decide` error (workflow.py:120-126, 144-150). The script stops only on `step`, so it keeps polling and then prints "STILL IN FLIGHT" for a ticket that has already ended.
- **Fix**: Also stop polling when `views[tid]["status"] != "running"`.
- **Decision**: FIXED — the poll now stops when `status != "running"` or `step == "awaiting_approval"`, and the sentence describing it was updated to match.

### F3 — The "no reason code" limitation names only `check`

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: README.md:427, README.md:444
- **Detail**: An unlisted `decide` error ends the same way: Temporal `failed`, `step` `deciding`, `failure_reason` `null` (workflow.py:120-123; covered by `test_unlisted_activity_error_still_fails_the_workflow`). The Known limitations bullet and the matching next step mention only `check`.
- **Fix**: Make both bullets say "an unlisted `decide` error or a `check` that runs out of attempts".
- **Decision**: FIXED — both the Known limitations and the Next steps bullets now cover an unlisted `decide` error as well as `check` exhaustion.

### F4 — GET description says "running workflow" for every ticket that isn't completed

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: README.md:161
- **Detail**: `api.py:132-142` reads the stored result only for `COMPLETED`. A running or failed ticket goes through a query, which a worker answers by replaying the history. README.md:213 already says this correctly for failed tickets.
- **Fix**: Change "otherwise asks the running workflow through a Temporal query" to "otherwise (running or failed) through a Temporal query".
- **Decision**: FIXED — wording applied as proposed.

### F5 — "also pinned by `tests/test_workflow.py`" is only partly true

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: README.md:78
- **Detail**: `test_workflow.py` pins the actions for T-2…T-7 through the real fake model. T-1 → KB-1 and the fake model's categories and priorities are pinned in `tests/test_agent.py` and `tests/test_api.py`.
- **Fix**: Say "pinned by the tests in `tests/`".
- **Decision**: FIXED — wording applied as proposed.

### F6 — Diagram has no approval edge into the wait node, and the end edge is unlabelled

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: README.md:119-150
- **Detail**: The plan's contract has `awaiting_approval (← POST /tickets/{ticket_id}/approval as a Temporal Update)`. The diagram shows the Update only on the client→API and API→Temporal labels, with no edge into the wait node. `act --> final` has no label. `direction TB` inside the subgraph is ignored by Mermaid, because its nodes link to nodes outside the subgraph.
- **Fix**: Add `temporal -. "approval Update" .-> wait`, label the end edge `"done / failed"`, and drop the ignored `direction TB`.
- **Decision**: FIXED — all three diagram edits applied. Verified in the actual VS Code Markdown preview: 11 nodes, 14 edges, no Mermaid error indicators; the dotted `approval Update` edge reaches the approval wait and the final edge shows `done / failed`. Screenshot and rendered SVG saved locally as `preview-current.png` and `diagram-current.svg` in the temporary `atw-s09-review` directory.

### F7 — Overview is 5 sentences instead of 2–3

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: README.md:3
- **Detail**: All the facts in the contract are there. Two extra sentences ("The model proposes; the code decides." and "It runs locally…") make it longer than the plan's 2–3 sentences.
- **Fix**: Merge into 3 sentences without dropping a fact.
- **Decision**: FIXED — merged into 3 sentences; no fact dropped.

### F8 — Real-model example puts the API key on the command line

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: README.md:295 (text from before this change; only moved)
- **Detail**: `LLM_API_KEY=sk-...` is a placeholder, but a real key typed this way stays in shell history.
- **Fix**: Add "prefer `.env` for the key: an inline key stays in shell history".
- **Decision**: FIXED — added the shell-history note to the Real model section.
