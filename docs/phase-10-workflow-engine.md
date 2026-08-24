# Phase 10 — Workflow Engine

Status: implemented and accepted on 2026-08-24.

## Objective

Provide a provider-neutral, selected-business workflow coordinator that executes
immutable dependency graphs durably and can stop and resume at explicit owner,
wait, and child-agent checkpoints without confusing a reusable workflow with a
single task.

## Implemented scope

- `workflows` and immutable `workflow_versions` form the global definition
  registry. Every run pins an exact version and validates its schema-bound input.
- `workflow_runs`, `workflow_step_runs`, and `workflow_events` persist the complete
  selected-business lifecycle, per-step attempt budget, child-agent linkage,
  structured input/output, sanitized failure, compensation, and append-only
  aggregate history in PostgreSQL.
- Definition validation rejects missing references, duplicate keys, cycles,
  unsupported step types, malformed conditions, retry budgets above ten, and any
  tool outside the Phase 10 internal R0 allowlist.
- Steps support dependency ordering, input/step-output equality conditions,
  internal tool execution, pinned agent delegation, explicit owner checkpoints,
  durable waits, bounded tool/agent retries, and reverse-order compensation where
  a definition declares an internal compensation.
- Resume commands are idempotent per run/event/key. Approval rejection, exhausted
  retries, invalid output, and impossible progress produce deterministic durable
  failure types rather than fabricated success.
- RQ delivers execution only. The worker reconciles queued work and reclaims a run
  interrupted while `running`, with no more than three recoveries. It never
  advances a durable wait without an authenticated owner command.
- Protected API and `/workflows` UI expose the immutable graph, selected-business
  run ledger, current checkpoint, step attempts, child run linkage, failures,
  compensations, and complete event history.
- The seeded `durable-checkpoint-workflow@1` is a provider-free R0 acceptance
  graph with five steps: internal capture, conditional branch, owner checkpoint,
  durable wait, and deterministic completion.

## Boundary

An approval step is only a manual Phase 10 checkpoint. It does not classify risk,
evaluate policy, grant external tool authority, permit spend, or bypass the future
kill switch. External tools and provider side effects remain disabled. Phase 10
workflow events are aggregate history and do not implement the Phase 12 event bus.
No scheduler, autonomous loop, deployment provider, or provider-specific runtime
architecture is introduced.

## Acceptance evidence

The canonical verification run passed API and web formatting, lint, strict type
checking, 75 API tests, two web tests, production builds, a fresh migration through
`20260824_10`, process health, and the complete isolated HTTP/PostgreSQL smoke suite.
The smoke path executed the five-step workflow, evaluated its conditional branch,
stopped and resumed through approval and wait checkpoints, proved duplicate resume
idempotency, completed deterministically, retained five durable completed steps and
two owner-resume events, then ran the false branch and owner-rejection path to prove
deterministic failure and reverse compensation. It also enforced selected-business
isolation and rendered the protected workflow UI. Phase 10 makes no model-provider
call.
