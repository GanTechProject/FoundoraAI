# ADR-0014: Transactional task lifecycle with dependency gates and idempotent retries

## Status

Accepted on 2026-08-22.

## Context

Phase 09 requires durable goals and tasks, dependency enforcement, priority,
founder or agent ownership, the full declared task state set, due dates, safe
retries, and events. Existing Phase 03 business goals are already the selected-
business goal authority and should not be duplicated. Phase 10 workflow execution,
Phase 11 approval policy, and Phase 12's internal event bus are not authorized yet.

## Decision

- Reuse `business_goals` as the goal authority and optionally link each task to
  one goal in the same selected business.
- Store task state in PostgreSQL and serialize dependency and lifecycle mutations
  by locking the selected business and affected task rows.
- Use an explicit transition graph. Entering `queued` or `running` requires every
  direct dependency to be `completed`.
- Permit dependency changes only while a task is `draft`, `planned`, or `blocked`.
  Reject self-dependencies, cross-business references, and cycles before insert.
- Represent ownership as unassigned, founder, or agent. Agent ownership pins the
  current immutable agent version at task creation so history cannot be rewritten
  by a later registry version.
- Retry only a `failed` task, within its stored retry budget and after re-checking
  dependencies. A caller-supplied idempotency key is unique per task retry event;
  replay returns the already-applied result without consuming another retry.
- Append a task-local event for creation, dependency addition, lifecycle change,
  and retry in the same transaction as the state mutation.

## Consequences

The database remains the durable source of task truth, duplicate retry requests
are safe, blockers are inspectable, and all task data remains business-scoped.
Task events are aggregate history only; they do not publish, subscribe, or replace
the Phase 12 event bus. `waiting_approval` is representable but no approval is
granted or evaluated before Phase 11. Queued tasks are not executed by a workflow
engine in this phase.
