# ADR-0009: Resumable onboarding with an explicit founder-approved fact boundary

## Status

Accepted on 2026-08-22.

## Context

Phase 04 must collect broad business context, remain resumable, and ensure no AI assumption silently becomes fact. Phase 05 has not authorized a model gateway, provider, or credential configuration. Draft founder input, future AI proposals, and durable approved business facts therefore require visibly different states and storage semantics.

## Decision

- Each business may have one mutable onboarding draft, resolved only through the authenticated session's selected-business context.
- The draft advances through foundation, market, execution, brand/services, and review steps. Every mutation supplies the last observed revision; stale concurrent writes fail instead of silently overwriting newer input.
- Draft, review, and approved are explicit lifecycle states. Submission validates completeness and freezes a revision in review. Review data cannot be edited.
- Approval is a separate authenticated and CSRF-protected founder action. It copies the exact reviewed fields into a versioned `approved_business_profiles` row and records the approving owner and timestamp.
- Reopening creates an editable state without changing the last approved profile. Only another submit-and-approve cycle replaces approved facts and increments the profile version.
- The approved onboarding name updates the business registry name in the same transaction and respects the existing case-insensitive uniqueness constraint.
- Goals collected during onboarding remain strategic profile statements. They are not silently converted into Phase 03 operational goal records because no target date, tracking status, or mapping was approved.
- Services listed during onboarding are founder declarations, not verified integrations. No connection, credential, or provider state is fabricated.
- Phase 04 performs no AI generation. When a later authorized model gateway proposes interpretations, proposals must remain distinguishable from founder input and cannot enter the approved profile except through review and explicit approval.

## Consequences

Downstream business context must use only the approved profile when it needs established facts; it may show drafts or future suggestions only with their provenance and unapproved status. The extra review transition is intentional friction that prevents assumptions, stale browser writes, and partial data from becoming authoritative. AI adapters, provider validation, and business-brain consumption remain outside Phase 04.
