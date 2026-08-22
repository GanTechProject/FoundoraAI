# ADR-0002: Modular monolith with separated processes

- Status: Accepted
- Date: 2026-08-22

## Context

The product spans many domains but starts from a greenfield, single-owner repository. Premature distributed services would add failure modes and operational cost before domain behavior exists.

## Decision

Use a modular monolith with explicit domain boundaries and separately runnable web, API, worker, and scheduler processes. Share versioned domain/application packages; keep business logic out of delivery frameworks and scheduler code. Use PostgreSQL for durable state, Redis for queue/coordination concerns, and an object-storage abstraction.

## Consequences

Local and production operations remain comprehensible while workers can scale independently. Module boundaries make later extraction possible if measurements justify it. Cross-module shortcuts and duplicated worker logic are prohibited.
