# Phase 17 — Business Strategy

Status: **COMPLETE**

## Delivered scope

- Immutable `business-strategist@1`, an R0 `manual_advisory_only` contract with
  no tools or assigned skills.
- Mandatory input pinning of exactly one completed Phase 16 run from each of
  Market Research, Competitor Intelligence, and Customer Research.
- Revalidation of each pinned research run against its immutable version schema
  and semantic anti-invention rules before a strategy run can be queued.
- A complete proposed strategy schema covering opportunity assessment, value
  proposition, business model, pricing hypotheses, positioning, go-to-market,
  launch roadmap, risks, and assumptions requiring validation.
- Semantic validation requiring every strategy item to cite at least one exact
  founder-approved business fact and one exact supported research finding.
- Protected `/strategy` API and UI with optimistic version checking and a
  separate explicit founder approval action.
- A versioned `approved_business_strategies` selected-business domain, exposed
  to future phases through the Business Brain `approved_strategy` source.
- Transactional `strategy.approved` events with durable audit-consumer delivery.

## Evidence and approval boundary

The strategist cannot run from an onboarding draft, an unsupported finding, a
failed or cross-business run, or an incomplete research set. Its immutable run
input pins agent/run/version/context identities, supported finding references,
validated research output, and the exact approved-fact references available in
the compiled business context. Runtime output validation rejects missing
artifacts, duplicate item IDs, altered or invented references, mismatched
context identity, or any artifact lacking both kinds of evidence.

Agent output always has `strategy_status: proposed`. It cannot approve itself.
Only the authenticated founder can promote a completed, revalidated strategist
run through the CSRF-protected approval endpoint. Approval creates or replaces
the current selected-business strategy, increments its version, preserves its
source run, context, and evidence references, and emits a transactional event.

Pricing remains explicitly hypothetical: every pricing item must use
`validation_status: requires_validation`. Every assumption must state a
validation method. Approval records the founder's chosen strategy direction; it
does not falsely turn research limitations, prices, or assumptions into proven
facts.

## Provider and phase boundary

The strategist uses the existing provider-independent model gateway. Research
comes from the Phase 16 `SearchProvider` boundary and is pinned before strategy
execution; Phase 17 adds no search, model, hosting, deployment, payment, or
communications provider. The agent cannot build or change products, offers,
brands, websites, campaigns, tasks, workflows, policy, memory, or knowledge and
cannot spend, contact people, launch, or claim an external action occurred.

Phase 18 product and offer implementation is not included. Phase 17 stops after
making approved strategy available as a traceable input to that future phase.

## Acceptance evidence

Migration `20260825_17` creates the approval table and seeds the strategist.
The deterministic suite includes 131 API tests and both web tests, strict Python
and TypeScript checks, production builds, migration round-trip verification,
contract/CSRF/protected-UI smoke coverage, and five healthy primary Docker
services. No model-provider call is needed for the Phase 17 deterministic gate;
model use occurs only when the founder explicitly queues a valid strategist run.
