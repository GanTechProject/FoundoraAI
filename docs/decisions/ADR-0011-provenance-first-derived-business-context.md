# ADR-0011: Provenance-first derived business context

## Status

Accepted on 2026-08-22.

## Context

Later agents and workflows need a unified view of a business, but the implemented
domains currently have different authority and lifecycle semantics. Onboarding
drafts are not approved facts, completed goals are stale for current planning, and
many future source domains do not yet exist. Context also has to fit bounded model
requests without coupling the core application to a provider tokenizer.

## Decision

- Build context on demand from durable authoritative records for the authenticated
  session's selected business; do not persist a second mutable context snapshot.
- Admit only live owner-controlled workspace data, founder-approved onboarding
  data, and current operational goals. Never read onboarding drafts as context.
- Represent every candidate with authority, reference, version, timestamp,
  validity, decision, exclusion reason, estimate, and hash. Omit excluded content
  while retaining its safe provenance metadata.
- Mark completed goals stale and cancelled goals invalidated. Both are excluded
  before source selection or budgeting.
- Use canonical JSON, fixed source priority, and a conservative one-token-per-byte
  upper bound. A source is included only when the complete payload remains within
  the caller's explicit budget.
- Report unimplemented future sources as unavailable instead of inferring or
  fabricating them.
- Keep context assembly provider-independent. Model execution remains behind the
  Phase 05 gateway, whose total request budgets still apply.

## Consequences

Context is business-specific, inspectable, deterministic for identical source
versions and controls, and safe from known stale or invalidated knowledge. The
conservative estimator may leave usable model capacity unused, but it guarantees
the context itself does not exceed its declared budget without depending on an
external tokenizer. On-demand derivation avoids a new synchronization problem;
later knowledge and memory phases can extend the candidate interface while
preserving authority, validity, and provenance rules.
