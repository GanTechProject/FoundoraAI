# ADR-0022: Immutable, founder-approved product and offer portfolio versions

Status: Accepted

Date: 2026-08-25

## Context

Phase 18 must turn an approved business strategy into structured products,
services, packages, pricing, benefits, and target segments. Agent output is
probabilistic and advisory; it must not silently become founder-approved business
data. Later brand and build phases also need a stable current portfolio without
losing the earlier approvals that explain how it changed.

## Decision

Seed `product-offer@1` as an immutable R0, manual-advisory-only contract. A run
requires and pins the exact current approved strategy version, source run, payload,
context, and item allowlist. Every proposed segment, product/service, benefit, and
package must cite that allowlist; all internal references must resolve. Pricing is
explicit but remains marked `requires_validation`.

Keep proposal generation separate from a CSRF-protected founder approval. Each
approval revalidates the pinned agent schemas and semantic rules, rejects a stale
strategy, creates a new immutable `product_offer_versions` payload, and supersedes
the former active version. A PostgreSQL partial unique index permits exactly one
active version per business. The approval publishes `product_offer.approved` in the
same transaction. Only the active founder-approved version enters the Business
Brain as `products_services` with `founder_approved_product_offer` authority.

## Consequences

- Agent output can never self-approve, launch, sell, deliver, or validate an offer.
- Historical approved payloads remain inspectable instead of being overwritten.
- Later phases receive one stable active portfolio plus exact strategy provenance.
- Changing the approved strategy does not mutate prior offers; a proposal tied to a
  stale strategy cannot be approved.
- The design adds no model, search, payment, deployment, or communications provider.

## Supersession

This decision extends ADR-0011, ADR-0012, ADR-0017, and ADR-0021. It does not
supersede them.
