<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Reviewer-Ready README Implementation Plan

- **Plan**: `context/changes/reviewer-readme-complete/plan.md`
- **Mode**: Deep
- **Date**: 2026-11-08
- **Verdict**: REVISE → SOUND after triage
- **Findings**: 0 critical, 2 warnings, 2 observations

Second review pass. The first pass (same date; F1 T-2 walkthrough order, F2 failure rate changes outcomes, F3 diagram API details) was triaged and all three were fixed in plan.md before this pass. This report replaces it, as the skill specifies one plan-review per change.

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding

Grounding: 6/6 paths ✓, 8/8 symbols ✓ (`DECIDE_RETRY`/`CHECK_RETRY`/`ACT_RETRY`, `REJECT_DUPLICATE`, the 3 named tests, `HELPDESK_FAILURE_RATE` compose interpolation), brief↔plan ✓, Progress↔Phase ✓ (1.1–1.5, 2.1–2.9).

The first pass's fixes (submit-and-poll before the T-2 walkthrough, rate-0 verification, full approval route and GET read path) were re-checked and add no new issues. Verified in code: T-4 → KB-4 and T-6 → `refund_amount_above_invoice` are pinned by `run_real` tests, the late-approval guard at `workflow.py:234`, the NaN serializer at `models.py:35-36`, and the Docker image installs the package with its `data/` files. No runtime tests were run.

## Findings

### F1 — Renamed "### Limitations" contradicts the plan's own anchor rule

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 §1 mapping vs §3 anchor fixes; Phase 2 §6
- **Detail**: Phase 1 renamed `## Known limitations` to `### Limitations`, while §3 required `#known-limitations` (README.md:145) to keep resolving. The Azure section already has `### Limitations` (README.md:243) and comes earlier in the new order, so the new heading would get `#limitations-1`.
- **Fix**: Name the final subsection `### Known limitations` in Phase 1 §1 and Phase 2 §6.
- **Decision**: FIXED — plan.md Phase 1 §1 and Phase 2 §6 now name `### Known limitations` explicitly, with the reason.

### F2 — `check` running out of retries has no outcome in the Reliability contract

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 §2 (Reliability contract)
- **Detail**: The contract gave every activity's exhaustion as "escalate with code / fail the ticket". `decide` and `act` have handlers; `check` does not (`workflow.py:144-150`). After 3 attempts the raw ActivityError fails the workflow: Temporal status `failed`, `step` stays `checking`, `failure_reason` null. The README never says this. It is unlikely in practice (check reads local files), but it is a gap against "every ticket ends with a clear reason". In this docs-only slice it is documented, not fixed.
- **Fix**: Spell out the `check` row (10 s, 3 attempts, 1 s → 2 s; on exhaustion fails at `checking` with no `failure_reason`), add a Known limitations bullet, and add a next step to map it to a reason code.
- **Decision**: FIXED — plan.md Phase 1 §2 contract names all three exhaustion outcomes; Phase 2 §6 adds the limitation bullet and the next step.

### F3 — Anchor check "a script" is unspecified

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Success criteria 1.1 / 2.2
- **Detail**: The check has to follow GitHub's slug rules: lowercase, punctuation and backticks dropped, spaces → hyphens, `-1`/`-2` suffixes for duplicates. A naive check would miss the F1 case.
- **Fix**: Use a throwaway `uv run python` script in the scratchpad (not committed) that follows those rules, duplicate suffixes included.
- **Decision**: FIXED — both anchor criteria now specify the scratchpad slug script and its rules.

### F4 — Quick start asks for a mid-flow compose restart

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Desired End State item 2; Phase 2 §3 prerequisite
- **Detail**: Quick start opened with `docker compose up --build` at the default 0.3. The submit-and-poll prerequisite then needed `HELPDESK_FAILURE_RATE=0 docker compose up --build`, so a reviewer reading top to bottom had to restart compose halfway through.
- **Fix**: Show both start commands at the top of Quick start; the loop's prerequisite points back to them.
- **Decision**: FIXED — Desired End State item 2 lists both start commands up front; the Phase 2 §3 prerequisite points back to the rate-0 command.
