---
bootstrapped_at: 2026-11-05T19:52:09Z
starter_id: fastapi
starter_name: FastAPI
project_name: agentic-ticket-workflow
language_family: python
package_manager: uv
cwd_strategy: native-cwd
bootstrapper_confidence: first-class
phase_3_status: ok
audit_command: pip-audit
---

## Hand-off

Source: `context/foundation/tech-stack.md`

```yaml
starter_id: fastapi
package_manager: uv
project_name: agentic-ticket-workflow
hints:
  language_family: python
  team_size: solo
  deployment_target: azure-container-apps
  ci_provider: github-actions
  ci_default_flow: manual-promotion
  bootstrapper_confidence: first-class
  path_taken: standard
  quality_override: false
  self_check_answers: null
  has_auth: false
  has_payments: false
  has_realtime: false
  has_ai: true
  has_background_jobs: true
```

### Why this stack

A solo developer is building a small Python API with a 1-week MVP and a hard deadline, so a mainstream, agent-friendly starter is the safest choice. FastAPI is the recommended default for Python APIs. It passes all four agent-friendly checks, and its Pydantic schemas fit the PRD's strict checks on every decision (allowed values; a refund only for the customer's own invoice, never above its amount). Scaffolding should work, though it may need an occasional manual step. FastAPI provides only the HTTP layer. Durable processing (asynchronous intake, the 24 h approval wait, retries without repeated actions, surviving restarts) runs on Temporal, with a separate worker, and the agent uses an LLM provider or a fake rule-based mode chosen by a setting. All of it runs locally with Docker Compose and no API key. Azure Container Apps is the deployment target described in the README, and optionally in IaC; nothing is actually deployed. CI uses GitHub Actions to run the tests on every push. Auth, payments and realtime are out of scope according to the PRD's Access Control and Non-Goals sections.

(The hand-off also carries a `## Required technologies` section: Python, FastAPI, Temporal, LLM with tool calling + fake mode, Docker Compose, env vars + `.env.example`, structured JSON logs, Temporal `WorkflowEnvironment` tests; optional GitHub Actions, OpenTelemetry, Terraform/Bicep, Azure. Not acted on by bootstrapper — see `context/foundation/tech-stack.md`.)

## Pre-scaffold verification

| Signal      | Value   | Severity | Notes                                                                                  |
| ----------- | ------- | -------- | -------------------------------------------------------------------------------------- |
| npm package | not run | n/a      | non-JS starter                                                                         |
| GitHub repo | not run | n/a      | card `docs_url` is `https://fastapi.tiangolo.com` (not GitHub) — no recency signal available |

Context: registry card `last_updated: 2026-04-22`; local toolchain `uv 0.13.1`; resolved `fastapi==0.162.0`, `uvicorn==0.54.0` from PyPI at scaffold time.

## Scaffold log

**Resolved invocation**: `uv init . && uv add fastapi uvicorn`
**Strategy**: native-cwd
**Exit code**: 0
**Pre-flight files-to-touch**: pyproject.toml, .python-version, main.py, uv.lock, .venv/ (README.md skipped if present)
**Files written by CLI**: 4 tracked-candidate files — `pyproject.toml`, `.python-version`, `uv.lock`, `src/agentic_ticket_workflow/__init__.py` — plus `.venv/` (CPython 3.11.9)
**Pre-existing files preserved**: all (README.md checksum unchanged; context/, CLAUDE.md, AGENTS.md, docs/ untouched)

Notes:
- uv 0.13.1 produced a packaged src-layout project (`uv_build` backend, `[project.scripts] agentic-ticket-workflow = "agentic_ticket_workflow:main"`) rather than the pre-flight-expected flat `main.py`.
- `.gitignore`: absent in cwd and not created — uv skips `.gitignore` when cwd is already inside a git repo. `.venv/` is therefore currently untracked-but-not-ignored.
- Installed 15 packages: agentic-ticket-workflow 0.1.0 (editable), annotated-doc 0.0.5, annotated-types 0.8.0, anyio 4.16.0, click 8.5.0, fastapi 0.162.0, h11 0.16.0, idna 3.20, opentelemetry-api 1.45.2, pydantic 2.14.3, pydantic-core 2.50.4, starlette 1.10.0, typing-extensions 4.16.0, typing-inspection 0.4.5, uvicorn 0.54.0.

## Post-scaffold audit

**Tool**: pip-audit (run as `uvx pip-audit --format json -r <uv export --no-hashes --no-emit-project>`; pip-audit not on PATH, so run ephemerally via uvx against the locked set)
**Exit code**: 0
**Summary**: 0 CRITICAL, 0 HIGH, 0 MODERATE, 0 LOW
**Direct vs transitive**: not distinguished by this tool (14 audited packages: 2 direct — fastapi, uvicorn — and 12 transitive)

#### CRITICAL findings

None.

#### HIGH findings

None.

#### MODERATE findings

None.

#### LOW / INFO findings

None.

## Hints recorded but not acted on

| Hint                    | Value                |
| ----------------------- | -------------------- |
| bootstrapper_confidence | first-class          |
| quality_override        | false                |
| path_taken              | standard             |
| self_check_answers      | null                 |
| team_size               | solo                 |
| deployment_target       | azure-container-apps |
| ci_provider             | github-actions       |
| ci_default_flow         | manual-promotion     |
| has_auth                | false                |
| has_payments            | false                |
| has_realtime            | false                |
| has_ai                  | true                 |
| has_background_jobs     | true                 |

## Next steps

Next: a future skill will set up agent context (CLAUDE.md, AGENTS.md). For now, your project is scaffolded and verified — happy hacking.

Useful manual steps in the meantime:
- Add a `.gitignore` (at minimum `.venv/`, `__pycache__/`, `.env`) before your next commit — uv did not create one because the repo already existed.
- Review any `.scaffold` siblings the conflict policy created and decide which version of each file to keep (none were created in this run).
- Address audit findings per your project's risk tolerance — the full breakdown is in this log (none found).
- Add the remaining required stack pieces from `tech-stack.md` (`temporalio`, LLM client, Docker Compose, `.env.example`, pytest) as implementation begins.

## Post-bootstrap changes

### 2026-11-05 — Python 3.11 → 3.14

Python 3.15.0 was ruled out for now: PyYAML (pulled in by `uvicorn[standard]`) had no 3.15 wheel, while the full required stack installed from prebuilt wheels on 3.14.8.

- `.python-version`: `3.11` → `3.14` (`uv python pin 3.14`)
- `pyproject.toml`: `requires-python = ">=3.11"` → `">=3.14"`
- `.venv/`: recreated with CPython 3.14.8 (`uv sync`)
- `uv.lock`: re-locked; still 15 packages at unchanged versions (`fastapi==0.162.0`, `uvicorn==0.54.0`); `uv lock --check` passes
- Audit: not re-run; the locked package set is unchanged, so the 0-findings result above still applies
- Smoke test: `import fastapi, uvicorn` succeeds on 3.14.8
