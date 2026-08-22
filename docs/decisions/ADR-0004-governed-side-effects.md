# ADR-0004: Govern all external and risky side effects

- Status: Accepted
- Date: 2026-08-22

## Context

Foundora will use agents and providers to perform actions that may communicate publicly, spend money, change infrastructure, or affect business/customer data.

## Decision

All agent actions follow Agent -> Skill -> Workflow/Tool -> Policy -> Provider. Enforce risk and approval beneath the model layer. Default autonomy to `OFF` or `RECOMMEND`; require approval for R3/R4 actions initially; prohibit R5 actions. Persist action state, idempotency keys, approvals, provider references, and audit evidence. Missing capability or credentials must produce a disabled/error state rather than simulated success.

## Consequences

Agents cannot bypass governance through prompts or direct integration ownership. Provider work carries additional contract, error, timeout, rate-limit, retry, observability, and idempotency requirements.
