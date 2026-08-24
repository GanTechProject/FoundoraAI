# ADR-0016: Execution-time governance with immutable policy evidence

## Status

Accepted on 2026-08-25.

## Context

Phase 11 must classify actions, require approval for R3/R4, enforce spend and
tool limits, support bounded autonomy, and provide a global kill switch. An
approval recorded during planning cannot be treated as permanent authority:
the kill switch, tool permission, spend remaining, or active policy may change
before execution. Provider-specific tools are not authorized in this phase.

## Decision

- Keep a code-reviewed provider-neutral action and tool catalog. Callers select
  an action contract; they do not select or lower its risk class. Any requested
  spend escalates classification to at least R4.
- Store the default policy separately from its immutable version and pin every
  governed action to the exact version that evaluated it.
- Persist business-scoped governance settings, tool permissions, action
  requests, approval requests, and append-only audit events in PostgreSQL.
- Default autonomy to `OFF` and spend limits to zero. `RECOMMEND` and
  `ASSISTED` require owner approval for autonomous proposals;
  `AUTONOMOUS_LOW_RISK` permits only R0/R1 without approval. R2, R3, and R4
  require owner approval, while R5 is denied.
- Treat approval and authorization as separate transitions. Approval records an
  owner decision. Authorization rechecks the active policy, global kill switch,
  selected-business tool permission, data boundary, and current spend ceilings
  immediately before execution.
- Enforce the policy gate beneath Phase 10 workflow prompts for every internal
  tool, compensation, and owner checkpoint. Workflow approval steps now link to
  the durable governance action and approval records.
- Keep the public action-evaluation endpoint owner-authored. Workflow and future
  agent/system actors can enter only through validated internal services, so an
  API caller cannot impersonate an internal actor.
- Expose authorization state rather than claiming an external side effect. No
  provider adapter or external tool is added by this decision.

## Consequences

- R3/R4 actions cannot receive execution authority without a durable owner
  approval, and a rejected approval remains terminal.
- A previously approved action can still be blocked by a later kill switch,
  policy change, permission change, or spend exhaustion.
- Authorized spend is conservatively reserved for the current UTC day; later
  provider phases may add consumption/release detail without weakening caps.
- The global kill switch is shared across businesses, while autonomy, spend,
  actions, approvals, and tool permissions remain selected-business scoped.
- Phase 12 domain events and all provider-specific side effects remain deferred.
