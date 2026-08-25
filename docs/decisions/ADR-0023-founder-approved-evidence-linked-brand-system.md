# ADR-0023: Founder-approved, evidence-linked brand system

Status: Accepted

Date: 2026-08-25

## Context

Phase 19 must turn approved strategy and product/offer direction into reusable
brand strategy, positioning, naming analysis, voice, messaging, tagline, visual
direction, rules, and asset references. Later content and website phases need one
stable set of approved rules, but probabilistic agent output must not silently
become founder-approved business direction. Brand artifacts also must not imply
that a name, domain, trademark, or creative asset was checked or created.

## Decision

Seed `brand-strategist@1` as an immutable R0, manual-advisory-only contract. A run
requires and pins the exact current founder-approved strategy and the active
founder-approved product/offer portfolio derived from that strategy, including
their source runs, payload versions, contexts, payloads, and complete reference
allowlists. Every proposed artifact must cite at least one exact strategy item and
one exact product/offer item. Naming availability remains `not_checked`, and asset
references remain `proposed_reference`.

Keep proposal generation separate from a CSRF-protected founder approval. Approval
revalidates the pinned schemas and semantic rules, rejects stale strategy or offer
evidence, creates an immutable `brand_system_versions` payload, and supersedes the
former active version. A PostgreSQL partial unique index permits one active version
per business. The approval publishes `brand.approved` in the same transaction. Only
the active founder-approved version enters the Business Brain as `brand` with
`founder_approved_brand_system` authority; its `brand_rules` remain directly
retrievable for later content agents.

## Consequences

- The agent cannot self-approve, publish, create assets, or claim name, domain, or
  trademark availability.
- Historical approved brand systems remain inspectable instead of being overwritten.
- Later phases receive one stable brand system plus exact strategy and offer
  provenance.
- A proposal cannot be approved after either of its source approvals becomes stale.
- The design adds no model-specific, creative, domain, trademark, hosting, or
  publishing provider.

## Supersession

This decision extends ADR-0011, ADR-0012, ADR-0017, ADR-0021, and ADR-0022. It does
not supersede them.
