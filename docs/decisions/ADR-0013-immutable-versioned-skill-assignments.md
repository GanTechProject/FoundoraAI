# ADR-0013: Immutable skill versions with exact agent assignments

## Status

Accepted on 2026-08-22.

## Context

Phase 08 introduces reusable agent capabilities. A compatibility declaration is
useful for discovery, but treating compatibility as authorization would allow an
agent to invoke capabilities it was never granted. Mutable skill definitions would
also make historical runs impossible to evaluate against their actual schemas,
permissions, and rubric.

## Decision

- Store skill identity separately from immutable skill versions. Every version
  declares its description, compatible agents, prerequisites, schemas, required
  tools, declarative workflow, permissions, risk class, fixtures, and rubric.
- Authorize invocation only through an exact `(agent_version_id,
  skill_version_id)` assignment. Both API enqueue and worker claim re-check this
  relationship, the agent allowlist, skill enablement, and compatibility.
- Pin an invoked skill version on the durable agent run and validate its input
  before enqueue and again before provider execution. Validate model output
  against the pinned skill output schema.
- Seed three harmless R0, tool-free skills. Assign only `summarize-business-context`
  to runtime verification agent version 2 so denial of a compatible but
  unassigned skill is directly testable.
- Treat the workflow field as declarative metadata only. Phase 08 does not build
  the Phase 09 task engine, Phase 10 workflow engine, Phase 11 policy engine, or a
  tool runtime.

## Consequences

Compatibility and authorization remain distinct, historical executions retain the
contract actually used, and later registry versions cannot rewrite old evidence.
Skill execution is intentionally limited to model-only, read-only R0 behavior
until later phases add governed tools, workflows, policies, and approvals.
