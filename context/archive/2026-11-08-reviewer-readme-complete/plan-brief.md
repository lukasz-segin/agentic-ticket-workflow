# Reviewer-Ready README — Plan Brief

> Full plan: `context/changes/reviewer-readme-complete/plan.md`

## What & Why

FR-012 (roadmap S-09, the last slice of the milestone): a reviewer must be able to learn from the README how to run, call, test, understand and deploy the service, and how AI assistants were used. The current README is correct but ordered for running the service, and it leaves out the architecture, the AI-usage story, and the assumptions and next steps.

## Starting Point

`README.md` (249 lines) already covers the one-command run, tests, T-1/T-2 walk-throughs, decision rules, failure handling, the real and fake models, and a complete Azure section. Retry, timeout and duplicate handling is spread over four places. There is no overview, diagram or "why it runs where".

## Desired End State

A README with one heading per FR-012 checklist item: Overview, Quick start (with all seven example tickets submitted in one paste and an outcome table), Architecture (Mermaid diagram plus a table of where each part runs and why), Reliability, Rules vs ticket text (T-6 worked through), Models, Tests, Azure, How AI assistants were used, and Assumptions/limitations/next steps. Every example has been checked on a live `docker compose up`.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Structure | Reorganise by FR-012 checklist | A reviewer can tick each item against a heading. |
| Diagram | One Mermaid flowchart | GitHub renders it, and it stays diffable text. |
| Example tickets | One submit-and-poll command (inside the `api` container) + an outcome table at `HELPDESK_FAILURE_RATE=0`, before the T-2 approval walk-through | Reproduces all seven outcomes with only Docker on the host (no jq); the 0 rate and the order keep the table exact. |
| AI tools named | Claude Code (builds), Gemini and Codex/ChatGPT (independent reviewers), human triages | Matches the multi-reviewer trail in `context/archive/*/reviews/`. |
| Wrong-output examples | S-06 late approval + S-04 NaN refund | Both are on the money path, and the second shows a wrong *fix* being caught too. |
| Code changes | None; a README/code mismatch is fixed in the README | Keeps this a docs-only slice. |

## Scope

**In scope:** README reorganisation; overview; architecture and diagram; a reason for where each part runs; the T-1…T-7 loop and table; a consolidated Reliability section; the T-6 walk-through; the AI section; assumptions, how no-auth would be secured, next steps.

**Out of scope:** any code/test/config change; rewriting the Azure section; FR-013…FR-016 work; extra diagrams or docs pages.

## Architecture / Approach

Phase 1 only moves and merges existing text under the new headings, so the diff is easy to review and no tested fact is lost. Phase 2 writes the new prose, taking every number (timeouts, attempts, step names, test names) from the code, then runs the README's own commands against compose to prove the outcome table.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Restructure existing content | Checklist headings, merged Reliability section, fixed anchors | Losing a sentence while merging duplicates |
| 2. New content + live verification | Overview, diagram, T-1…T-7 loop/table, AI section, assumptions/next steps | The table assumes a fresh history at failure rate 0; at the default 0.3 a ticket can end `helpdesk_unavailable` |

**Prerequisites:** S-02, S-03, S-06, S-07 and S-08 done (they are); Docker for the live run.
**Estimated effort:** about 1 session, 2 phases.

## Open Risks & Assumptions

- The AI-tool roles are as stated by the user (Claude Code builds, Gemini and Codex/ChatGPT review).
- The live run may reveal a README/code mismatch. It is corrected in the README, and any real bug is reported separately.

## Success Criteria (Summary)

- Each FR-012 checklist bullet maps to a named README heading.
- Pasting the Quick start commands into a fresh `docker compose up --build` reproduces the T-1…T-7 table.
- The AI section names the tools and tells two verified wrong-output stories, with the tests that now guard them.
