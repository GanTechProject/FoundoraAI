# ADR-0021: Founder-approved, evidence-linked business strategy

Status: Accepted

Date: 2026-08-25

## Context

Phase 17 must turn approved business facts and Phase 16 research into a usable
strategy without allowing a model proposal to silently become authoritative.
Future product and offer phases need a stable strategy source with exact
provenance, while strategy generation must remain provider-neutral and advisory.

## Decision

Business Strategist runs pin one completed, semantically valid run from every
Phase 16 research role and the exact approved-fact references in their Business
Brain context. Every output artifact cites both allowlists and remains proposed.

A separate authenticated founder action revalidates and promotes a selected run
to the versioned `approved_business_strategies` domain. The current version is
then exposed by Context Service as `approved_strategy` with
`founder_approved_strategy` authority. Approval and its audit event commit in the
same PostgreSQL transaction.

## Consequences

- Model output cannot self-approve or become a business fact merely by existing.
- Future phases receive one selected-business strategy source with immutable run,
  context, and evidence lineage.
- Research gaps block strategy generation instead of being filled by invention.
- Pricing and assumptions remain visibly subject to validation after approval.
- No model, search, deployment, or external-action provider is selected by this
  design.
