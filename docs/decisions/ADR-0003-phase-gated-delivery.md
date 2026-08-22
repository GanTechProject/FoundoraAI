# ADR-0003: Strict phase-gated, evidence-based delivery

- Status: Accepted
- Date: 2026-08-22

## Context

The master specification defines 63 ordered phases and forbids claiming generated but unwired behavior as complete.

## Decision

Implement exactly one authorized phase at a time. Begin with the prescribed start report, verify the definition of done, publish the completion report, then stop for explicit founder authorization. Introduce future-facing interfaces only when the active phase requires them.

## Consequences

Progress may appear slower than broad scaffolding, but status remains auditable and regressions are attributable. Future phases remain `NOT IMPLEMENTED` until their acceptance criteria are actually verified.
