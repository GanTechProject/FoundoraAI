# Phase 07 - Agent Registry & Runtime

Status date: 2026-08-22

## Scope delivered

- durable `agents` and immutable `agent_versions` registry records;
- durable business-scoped `agent_runs` and ordered `agent_messages`;
- the required `queued`, `running`, `waiting_tool`, `waiting_approval`,
  `completed`, `failed`, and `cancelled` state vocabulary;
- structured input and output contracts with strict validation;
- worker-owned asynchronous execution through Redis/RQ and the Phase 05 model
  gateway;
- selected-business run creation, dashboard and individual inspection, and
  authenticated cancellation through protected API and `/agents` UI;
- direct model-attempt linkage from `model_gateway_calls.agent_run_id`, sharing the
  operation ID stored on each claimed run;
- migration `20260822_06`, including one executable verification-agent version.

## Seeded agent contract

`runtime-verification-agent` version 1 is intentionally narrow. It inspects only a
bounded Phase 06 context snapshot and returns a summary, up to five observations,
and an escalation flag. The version records role, purpose, responsibilities and
non-responsibilities, task types, empty skill/tool permissions, forbidden actions,
model policy, data scope, R0 risk, manual-only autonomy, schemas, evaluation
criteria, and escalation criteria.

Its context ceiling is 1,024 conservative context tokens, output is capped at 256
tokens, and the complete operation is capped at 8,192 tokens and 10,000 micro-USD.
That total budget is large enough for the governed fallback candidates to pass
preflight while remaining a hard ceiling. Provider choice remains configuration
driven and provider-independent.

## Lifecycle and truth boundaries

Creating a run resolves the authenticated session's selected business, compiles
approved context, validates and stores the structured input, pins the version, and
commits the run before enqueueing its identifier. The worker locks the durable row
before claiming it. Redis job results are discarded because PostgreSQL owns the
result and status.

Successful provider JSON must pass the pinned output schema before `completed` is
stored. Provider, schema, queue, and unexpected runtime failures become `failed`
with safe bounded error details and an ordered system message. No failure path
returns mock output. Cancelling a non-terminal run stores `cancelled` immediately;
queued jobs are skipped and late in-flight results cannot replace that state.

`waiting_tool` and `waiting_approval` are valid persisted states for the required
lifecycle, but the Phase 07 agent cannot enter them because its permissions are
empty and the corresponding engines are not implemented.

## API surface

- `GET /agents` returns the current registry versions and the latest 20 runs for
  the selected business;
- `POST /agents/{agent_id}/runs` creates a CSRF-protected queued run;
- `GET /agents/runs/{run_id}` inspects a run only in the selected business;
- `POST /agents/runs/{run_id}/cancel` durably cancels a non-terminal run.

Responses are not cached. An archived or unselected business cannot supply an
operational context, and another selected business receives 404 rather than run
details.

## Acceptance evidence

`./scripts/verify.ps1` covers formatting, lint, strict type checking, 54 backend
tests, frontend tests, production build, Compose validation, fresh migration,
service health, and the isolated end-to-end smoke suite. Phase 07 smoke evidence
proves:

- one real agent executes from HTTP enqueue through RQ worker, governed model
  fallback, schema validation, and durable completion;
- the run exposes pinned version, input, output, messages, operation identity, and
  linked provider attempts without leaking keys or raw prompts;
- selected-business context includes the selected business and excludes another;
- one queued run cancels and remains cancelled when its job is later consumed;
- a deliberately corrupted queued input fails deterministically and persists the
  honest schema error;
- PostgreSQL contains exactly the expected completed, failed, and cancelled run
  evidence in the isolated database, and the protected `/agents` UI renders it.

## Explicitly not implemented

At Phase 07 completion, skills were not implemented. Phase 08 subsequently added
the isolated skill registry without changing this phase's historical evidence.
Tool execution, approval decisions, registry editing, autonomous scheduling,
external side effects, deployment-provider architecture, and later specialist
agents remain unimplemented.
