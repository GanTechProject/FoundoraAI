# Phase 15 — Executive Agents

Status: **COMPLETE**

## Delivered scope

- Immutable `founder-ceo@1` and `chief-of-staff-planning@1` registry contracts.
- Founder/CEO interpretation of a founder objective, selected-business state
  review, ordered priorities, rationale, risk, approval need, and proposed
  delegation or specialist-work requests.
- Chief-of-Staff conversion of an objective into proposed tasks with priorities,
  dependencies, candidate ownership, completion criteria, assumptions,
  limitations, founder decisions, and existing-task progress review.
- Automatic selected-business context snapshots using live/approved profile,
  goals, current tasks, and active curated memory. Draft onboarding and implicit
  knowledge retrieval remain forbidden.
- Durable plan traceability through run ID, pinned agent version, context ID,
  context SHA-256, exact source references, structured output, model operation,
  usage attempts, and lifecycle timestamps.
- Runtime semantic validation for exact evidence references, output/context
  identity, proposed-only status, R3–R5 approval preservation, allowed advisory
  targets, unique IDs, known dependencies, acyclic graphs, and current-task-only
  progress claims.
- Protected API and `/agents` UI inspection of the executive contracts, plan
  output, and explicit evidence trace.

## Authority boundary

Both agents are R0 and `manual_advisory_only`. They have no assigned skills or
allowed tools. A run cannot create, update, queue, assign, execute, or complete a
task or workflow; grant approval; alter policy; spend; contact people; access
credentials; or claim a proposed delegation occurred. Future specialist work is
explicitly labeled unavailable rather than represented as executed.

Phase 15 does not add a second plan table. The immutable agent run is the
traceable proposed plan artifact. Durable autonomous plan materialization is
reserved for Phase 43, where governance approval and execution boundaries can be
applied together.

## Durable model

Migration `20260825_15` seeds the two agent identities and their immutable
version-one contracts in the existing `agents` and `agent_versions` tables. No
provider, tool, task, workflow, or approval table is added.

## Acceptance evidence

Deterministic runtime tests prove that a CEO plan binds to its exact context and
source references without tools; unsupported evidence, mismatched context,
unsafe risk approval, executed-status claims, invalid candidates, unknown task
dependencies, dependency cycles, and fabricated progress references fail
honestly. API tests prove the explicit plan trace. Fresh upgrade/downgrade,
registry/UI, CSRF, selected-business, formatting, lint, strict typing, build,
and deterministic CI runtime gates pass. Final deterministic evidence includes
119 API tests, both web tests, migration `20260825_15`, and five healthy primary
services.

The isolated smoke suite reaches and passes the explicit Phase 15 contract and
protected-UI checkpoint. Its later legacy live-provider regression currently
stops honestly because the configured OpenAI credential returns 401 and Gemini
generation returns 429 quota responses. Provider validation still reaches
Gemini successfully; no Phase 15 failure or fabricated provider success is
hidden by this external state.

Phase 16 research agents and `SearchProvider` are not implemented. Phase 15
stops here.
