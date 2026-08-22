# Phase 08 — Skill Registry

Status: implemented; final acceptance is recorded by `./scripts/verify.ps1`.

## Objective

Introduce immutable, inspectable skill contracts and prove that an agent can
invoke only skill versions assigned to its exact immutable agent version.

## Implemented scope

- `skills` stores stable identity, display state, enablement, and the current
  version pointer.
- `skill_versions` stores immutable description, compatible agents,
  prerequisites, input/output JSON schemas, tool requirements, declarative
  workflow, permissions, R0–R5 risk class, test fixtures, and evaluation rubric.
- `agent_skill_assignments` grants an exact skill version to an exact agent
  version. Compatibility alone never grants execution permission.
- `agent_runs.skill_version_id` pins the invoked skill contract for inspection
  and historical evaluation.
- API enqueue validates assignment, compatibility, allowlists, enablement, and
  input schema. The worker independently re-checks the same authority and validates
  the pinned skill identity, input, unsupported tool requirements, and output.
- The protected `/agents` UI exposes the full registry but places only assigned
  skills in an agent's invocation control.

## Initial harmless skills

| Skill | Version | Risk | Tools | Assigned to runtime agent v2 |
|---|---:|---:|---|---|
| `summarize-business-context` | 1 | R0 | None | Yes |
| `generate-structured-plan` | 1 | R0 | None | No |
| `analyze-provided-data` | 1 | R0 | None | No |

All three are compatible with the runtime verification agent. This deliberately
proves that compatibility is not authorization.

## Boundary

No task engine, executable workflow engine, policy/approval engine, tool runtime,
external side effect, provider-specific deployment architecture, or autonomous
execution is introduced. The existing provider-independent model gateway remains
the only model boundary.

## Acceptance evidence

`./scripts/verify.ps1` performs the canonical acceptance run. It verifies
formatting, lint, type checking, 57 backend tests, frontend build, migration head
`20260822_07`, PostgreSQL and Redis reachability, worker health, all Docker Compose
services, three immutable skill records and versions, one exact assignment,
successful assigned-skill execution with pinned usage, and HTTP 403 denial for a
compatible but unassigned skill. Secrets remain in ignored local environment
configuration and are not logged or persisted by the skill registry.
