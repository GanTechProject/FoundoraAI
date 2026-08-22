# ADR-0012: Immutable agent versions with durable worker-owned runs

## Status

Accepted on 2026-08-22.

## Context

Agents need inspectable identity, permissions, model policy, structured contracts,
and historical behavior before later skills, tools, approvals, and autonomous
execution are introduced. Redis can transport work but cannot be the source of
truth for lifecycle or outcomes. Editing a registry entry in place would also make
past runs impossible to interpret reliably.

## Decision

- Store reusable agent identity separately from immutable agent versions. Every
  run pins one version and snapshots its structured selected-business input.
- Treat PostgreSQL as lifecycle truth. Redis and RQ carry only the run identifier;
  the worker claims and transitions the durable row transactionally.
- Support the complete Phase 07 state vocabulary while using only `queued`,
  `running`, and terminal states in the initial no-tool agent. Tool and approval
  waits remain unentered until their phases provide real behavior.
- Route all model work through the Phase 05 gateway with a shared operation ID and
  direct `agent_run_id` usage linkage. Never persist prompts, credentials, raw
  provider bodies, or fabricated success.
- Validate declared input before execution and provider JSON against the pinned
  output schema before completion. Persist a bounded safe error and error message
  when execution cannot produce a valid output.
- Make cancellation durable and cooperative. A queued cancelled run is ignored by
  the worker; a provider result arriving after cancellation is discarded.
- Seed one R0, manual-run-only verification agent with no skills, tools, credential
  access, or external effects. Later agents and registry-management behavior need
  their own authorized phases.

## Consequences

Runs are business-scoped, replay-inspectable as historical evidence, and resilient
to Redis result expiry. Model attempts, fallback lineage, messages, errors, and
terminal timestamps remain queryable together. The initial cancellation boundary
cannot interrupt an already in-flight provider HTTP request, but it prevents any
late result from changing the cancelled terminal state. The schema and state model
can admit real skills and approvals later without pretending those capabilities
exist now.
