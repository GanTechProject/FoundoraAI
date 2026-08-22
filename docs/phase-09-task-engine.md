# Phase 09 — Task Engine

Status: implemented and accepted on 2026-08-22.

## Objective

Provide a selected-business, durable task ledger with goals, dependency ordering,
priority, founder or version-pinned agent ownership, explicit lifecycle state,
due dates, bounded safe retries, and inspectable events.

## Implemented scope

- Existing `business_goals` remain the goal authority; a task may link to one goal
  only when both records belong to the selected business.
- `tasks` persists title, description, priority 1–5, owner, exact agent-version
  ownership when applicable, state, due timestamp, retry budget/count, sanitized
  last failure, creator, and timestamps.
- `task_dependencies` stores a directed acyclic dependency graph. Mutations lock
  the selected business, reject cross-business and self references, reject cycles,
  and stop once work is queued.
- `task_events` is append-only task history for creation, dependency addition,
  lifecycle transitions, and retries. State and event writes share one database
  transaction.
- The lifecycle supports `draft`, `planned`, `queued`, `running`, `blocked`,
  `waiting_approval`, `completed`, `failed`, and `cancelled` through a constrained
  transition graph.
- A task cannot enter `queued` or `running` until every dependency is completed.
- Retry requires `failed` state, remaining retry budget, satisfied dependencies,
  and a bounded idempotency key. Replaying the key returns the same state without
  incrementing the retry counter or appending a duplicate event.
- Protected API and `/tasks` UI expose real selected-business goals, task state,
  blockers, ownership, lifecycle actions, retry budget, and event history.
- The Business Brain now exposes current task state and dependency satisfaction as
  provenance-backed `current_tasks` context. Completed tasks are stale and
  cancelled tasks are invalidated.

## Boundary

Phase 09 does not execute queued tasks, define or run workflows, make approval
decisions, publish domain events, call tools, schedule work, or perform autonomous
actions. `waiting_approval` is lifecycle-compatible only. Those capabilities remain
in their later explicit phases.

## Acceptance evidence

The canonical verification run passed formatting, lint, strict type checking, 64
backend tests, frontend tests and production build, a fresh migration to
`20260822_08`, and every Phase 09 smoke assertion. The task path proved task and
event persistence, exact agent-version ownership, cycle rejection, blocked
queueing, successful dependency release, failed-state retry, duplicate retry
idempotency, cross-business isolation, protected UI rendering, and direct
PostgreSQL evidence. PostgreSQL, Redis, API, worker, and frontend remained healthy
through Docker Compose.

After those Phase 09 checks passed, the same full-regression command stopped in a
pre-existing live Phase 07/08 agent replay: OpenAI returned HTTP 401 and Gemini
returned HTTP 429 for all three bounded agent attempts. A preceding governed
Gemini gateway call returned HTTP 200. Foundora persisted those provider failures
honestly. Phase 09 adds no provider call or external dependency, so this external
quota condition does not invalidate its acceptance; it does mean the final
all-phase `./scripts/verify.ps1` invocation was not globally green at that moment.
