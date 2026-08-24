# ADR-0015: Version-pinned durable workflow coordination

## Status

Accepted on 2026-08-24.

## Context

Phase 10 requires workflows to remain distinct from tasks while supporting
versioned definitions, dependency-aware steps, conditional branches, agent and
tool execution, owner checkpoints, durable waits, retries, compensation where
possible, resumability, and deterministic failures. Phase 11 policy, risk, and
approval authority and Phase 12 domain events are not yet authorized.

## Decision

- Store reusable workflow identity separately from immutable versions. Every
  selected-business run pins one exact version and creates its complete step-run
  ledger before queue delivery.
- Keep PostgreSQL authoritative for run, step, retry, checkpoint, output,
  compensation, and append-only aggregate-event state. Redis/RQ only delivers
  resumable execution jobs.
- Validate each definition as an acyclic dependency graph. A step becomes ready
  only after every dependency is completed, skipped by a false condition, or
  compensated.
- Execute only a code-reviewed allowlist of internal R0 tools in this phase.
  Agent steps pin and delegate to the existing agent runtime. External tools
  remain disabled until later policy and provider phases authorize them.
- Treat an approval step as an explicit owner checkpoint, not a Phase 11 policy
  grant. Resume commands use caller idempotency keys; rejection fails the run
  deterministically.
- Retry tool and child-agent steps only within the pinned step budget. On terminal
  failure, run declared internal compensations in reverse completed-step order
  and preserve both original and compensation evidence.
- Reconcile lost queue delivery and reclaim interrupted running work at the worker
  boundary, with at most three recoveries. Waiting workflows are durable and are
  never polled or advanced implicitly.

## Consequences

Workflow history cannot be rewritten by registry changes, duplicate resume
commands are safe, waits survive process restarts, and provider-specific types do
not enter the domain. Phase 10 aggregate events are workflow history only, not the
Phase 12 publish/subscribe event bus. Policy-derived approvals, risk assessment,
spend authority, external tool permissions, and the kill switch remain Phase 11.
