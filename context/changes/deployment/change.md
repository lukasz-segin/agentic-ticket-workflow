---
change_id: deployment
title: Deployment, minimal definition of done (local run + Azure description)
status: planned
created: 2026-11-06
requirements: [FR-009, FR-012]
---

This change covers the minimal deployment deliverables:
- a `Dockerfile` for one image, used by both the API and the worker;
- a `.env.example` without real secrets;
- a 3-service `docker-compose.yml`: the Temporal dev server with its UI, the API and the worker, in fake LLM mode with no key;
- the README "Azure deployment" section.

Nothing gets deployed (PRD Non-Goal). Bicep/Terraform, CI and any deploy runbook are out of scope.

Plan: [deployment-plan.md](deployment-plan.md)
