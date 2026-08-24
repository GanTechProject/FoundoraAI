# ADR-0020 — Traceable advisory executive agents

Status: Accepted
Date: 2026-08-25

## Context

Phase 15 introduces the Founder/CEO and Chief-of-Staff/Planning roles. They must
interpret objectives, review business state, prioritize and decompose work, and
request specialist help without bypassing governance or implying that proposed
work occurred. The existing versioned agent runtime already provides durable
runs, pinned context, model usage, and honest failure state.

## Decision

- Both executive agents are immutable versioned registry contracts executed by
  the existing provider-independent model gateway and worker runtime.
- They are R0, manual, advisory-only agents with no skills, tools, credentials,
  spend, approval, task mutation, workflow mutation, or external side effects.
- A completed executive run is the Phase 15 plan artifact. It pins agent version,
  selected business, objective, context ID, context SHA-256, exact included
  source references, structured output, model operation, usage, and timestamps.
  A second plan authority is not introduced before autonomous planning.
- CEO priorities remain `proposed`, cite exact context source references, expose
  assumptions and limitations, classify risk, preserve mandatory approval for
  R3–R5 work, and request work only from the founder, Planning agent, or an
  explicitly labeled future specialist.
- Planning output remains `proposed`, uses unique task IDs, an acyclic dependency
  graph, completion criteria, honest candidate ownership, and evidence citations.
  Progress review can cite only exact included `current_tasks` references.
- Runtime validation occurs after JSON-schema validation and before persistence.
  A mismatched context ID, invented evidence reference, invalid delegation,
  unsafe risk claim, dependency cycle, or fabricated task-progress reference
  fails the run honestly as `agent_schema_invalid`.

## Consequences

- The owner can inspect why every proposed priority or task exists and which
  immutable snapshot supported it.
- Proposed delegation never queues another agent or creates a durable task.
  Autonomous plan materialization remains Phase 43 scope.
- Explicit executive runs may call whichever configured model is selected by the
  provider-independent gateway. Phase 15 adds no provider-specific architecture.
- Later agent versions may add governed skills, but authority must be assigned to
  that exact version and still cross workflow/tool policy boundaries.
