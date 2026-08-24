# Phase 11 — Policy, Risk & Approval Engine

Status: complete and verified on 2026-08-25.

## Implemented boundary

Phase 11 adds a provider-neutral governance layer beneath workflow execution:

- immutable versioned default policy and code-reviewed action/tool catalogs;
- code-derived R0–R5 classification, including automatic R4 escalation for any
  requested spend;
- selected-business autonomy controls (`OFF`, `RECOMMEND`, `ASSISTED`, and
  `AUTONOMOUS_LOW_RISK`);
- zero-by-default daily and per-action spend limits with an execution-time UTC
  daily reservation check;
- selected-business permissions for every currently executable internal R0
  workflow tool;
- a global owner-controlled kill switch with optimistic revision protection;
- durable governed actions, owner approval requests, terminal rejection, and a
  separate execution-authorization transition;
- append-only action, decision, control, permission, and execution audit
  evidence;
- protected API and server-rendered `/governance` console;
- workflow integration that checks tools and compensation beneath prompts and
  replaces Phase 10-only checkpoints with linked governance approvals.

The public proposal API cannot claim an agent, workflow, or system identity.
Those actors use validated internal service paths. The UI explicitly records
authorization only and never claims a message, publication, payment,
deployment, deletion, or provider action occurred.

## Safety rules

- R3 and R4 always require explicit owner approval.
- R5 is always denied.
- R2 uses the safe default of owner approval.
- A rejected approval cannot authorize.
- Approval does not freeze authority. The active policy version, kill switch,
  tool permission, restricted-data boundary, and spend remaining are checked
  again before authorization.
- Unknown actions and tools are denied by the catalog boundary.
- `OFF` denies autonomous execution; `RECOMMEND` and `ASSISTED` require an
  owner decision for autonomous proposals; `AUTONOMOUS_LOW_RISK` permits only
  R0/R1 without approval.
- External provider tools remain unavailable until their own phases add real
  adapters, credentials, idempotency, and provider acceptance tests.

## Persistence

Migration `20260824_11` adds:

- `policies` and `policy_versions`;
- `global_governance_controls`;
- `governance_settings` and `governance_tool_permissions`;
- `governance_actions` and `approval_requests`;
- `governance_audit_events`;
- the governance-action link on `workflow_step_runs`.

Existing businesses are backfilled with `OFF`, zero spend, and the three
current internal R0 tool permissions. New businesses receive the same defaults
transactionally with workspace creation.

## Acceptance evidence

The deterministic quality gate passed:

- Ruff format and lint;
- mypy for all 56 API source files;
- all 84 API tests;
- web formatting, lint, and TypeScript checks;
- both web tests;
- the Next.js production build, including `/governance`.

The isolated Docker/PostgreSQL smoke suite passed and proved:

- a fresh database migrates through `20260824_11`;
- unauthenticated governance access is rejected;
- R3 cannot authorize before approval and remains non-authorizable after
  rejection;
- R4 spend is denied at the zero default, requires approval inside configured
  caps, and is rechecked before authorization;
- low-risk autonomous authorization requires `AUTONOMOUS_LOW_RISK`;
- disabling an internal tool prevents a real workflow step from executing;
- engaging the global kill switch prevents a real workflow step beneath the
  prompt layer;
- governance actions and controls do not cross business boundaries;
- action, approval, denial, authorization, control, and kill-switch evidence is
  durable;
- the protected governance console renders only real persisted state;
- API, web, PostgreSQL, Redis, and worker remain healthy.

No live model-provider call is required or billed by Phase 11 verification.

## Deferred

Phase 12 domain events, external tool/provider adapters, provider-side spend
consumption, unrestricted autonomy, scheduler behavior, deployment selection,
and SaaS tenant controls are not implemented.
