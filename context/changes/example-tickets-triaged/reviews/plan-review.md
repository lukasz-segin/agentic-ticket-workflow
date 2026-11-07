<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Remaining Example Tickets Triaged Implementation Plan

- **Plan**: context/changes/example-tickets-triaged/plan.md
- **Mode**: Deep
- **Date**: 2026-11-07
- **Verdict**: REVISE → SOUND after triage
- **Findings**: 0 critical, 4 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding
Grounding: 7/7 paths ✓, 10/10 symbols ✓, brief↔plan ✓

## Findings

### F1 — Parametrized agent test asserts nonexistent reason on ReplyAction

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 — Changes Required: 2. Agent tests for the example tickets
- **Detail**: The contract specifies: "A parametrized test over T-3, T-4 and T-5 that asserts category, priority, action type and reason." However, T-4's action is a ReplyAction, which defines (type, message, article_ids) and has no reason attribute (models.py:25-29). A uniform assertion checking result.decision.action.reason across all three will raise AttributeError on T-4.
- **Fix**: Specify checking reason only for escalate/close actions (or getattr(action, "reason", None)), and checking article_ids == ["KB-4"] for T-4.
- **Decision**: FIXED

### F2 — decide error wrap must enclose downstream decided attribute access

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — Changes Required: 3. Workflow escalation
- **Detail**: The contract states: "Wrap the decide call in except ActivityError... Leave decision as None and tool_calls as [], log escalated before decision with reason_code, and go on to acting." In workflow.py:72-85, lines immediately following execute_activity("decide") read decided.decision and decided.tool_calls. If only the execute_activity statement is wrapped, an activity error leaves decided unassigned, causing an UnboundLocalError on line 72.
- **Fix**: Clarify that the normal post-decision handling (workflow.py:72-89) belongs inside the try: block (or an else: clause), bypassing directly to _enter("acting") on caught ActivityError.
- **Decision**: FIXED

### F3 — README doesn't describe the fake model's rules

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1
- **Detail**: FR-009 requires the README to say fake mode is simple and rule-based, and roadmap S-09 expects each slice to leave README notes. The plan doesn't touch README.md.
- **Fix**: Phase 1 adds a `### Fake model` subsection to README `## Run locally`, listing the rules, the fallback and the limits. A manual check is added (Progress 1.5).
- **Decision**: FIXED

### F4 — Keyword "can't use" never matches T-4

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Lean Execution
- **Location**: Phase 1 — Changes Required: 1
- **Detail**: T-4's body says "can't we use", so the substring "can't use" never matches. T-4 matches through "locked".
- **Fix**: Drop "can't use" from the T-4 rule's keywords.
- **Decision**: FIXED

### F5 — No guard that T-2 and T-6 stay unmatched

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 — Changes Required: 2
- **Detail**: The first matching rule wins (fake_llm.py:27). If an S-03 keyword matched T-2 or T-6, S-04's refund rules, added after it, would never be reached. The plan claims the keywords don't match them, but no test pins that.
- **Fix**: Add a test that T-2 and T-6 escalate with `no_matching_rule`.
- **Decision**: FIXED
