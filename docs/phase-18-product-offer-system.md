# Phase 18 â€” Product & Offer System

Status: **COMPLETE**

## Delivered scope

- Immutable `product-offer@1`, an R0 `manual_advisory_only` contract with no tools
  or assigned skills.
- Required pinning of the exact current founder-approved strategy version, source
  run, context, complete payload, and generated strategy-item reference allowlist.
- A complete proposal schema for target segments, products/services, benefits,
  packages, explicit pricing, lifecycle status, founder decisions, and limitations.
- Semantic validation of globally unique identifiers, all internal references, and
  exact approved-strategy citations for every business entity.
- Protected `/products-offers` API and UI with optimistic version checking and a
  separate CSRF-protected founder approval action.
- Immutable selected-business portfolio versions with one active version and
  preserved superseded history.
- Active approved portfolio retrieval through the Business Brain
  `products_services` source with founder-approved authority.
- Transactional `product_offer.approved` events with durable audit delivery.

## Evidence and approval boundary

The agent cannot run until the selected business has an approved strategy. Its run
input pins that strategy's version, source run, context, payload, and every eligible
item reference. The runtime rejects invented citations, duplicate identifiers,
missing segments/products/packages/benefits, unresolved internal references,
self-approved statuses, and pricing presented as validated.

Agent output always has `portfolio_status: proposed`; products and packages also
remain `proposed`. Only the authenticated founder can approve a completed,
revalidated run tied to the still-current strategy. Approval creates a new active
portfolio version and preserves the previous version as superseded. The stored
approval is authoritative founder direction, while each price still retains
`validation_status: requires_validation` so market evidence is not overstated.

## Provider and phase boundary

The agent uses the existing provider-independent model gateway. Phase 18 adds no
search, model, hosting, deployment, payment, sales, delivery, or communications
provider. It cannot launch or fulfill an offer, spend, contact people, or create
brands, websites, campaigns, tasks, workflows, policy, memory, or knowledge.

Phase 19 brand implementation is not included. Phase 18 stops after making the
active approved product and offer portfolio available as structured, traceable
business data.

## Acceptance evidence

Migration `20260825_18` creates the immutable portfolio-version table, active-row
constraint, and Product & Offer Agent. The deterministic suite includes 135 API
tests and both web tests, strict Python and TypeScript checks, production builds,
migration round-trip verification, contract/CSRF/protected-UI smoke coverage, and
five healthy primary Docker services. No model-provider call is needed for the
Phase 18 deterministic gate; model use occurs only when the founder explicitly
queues a valid Product & Offer Agent run.
