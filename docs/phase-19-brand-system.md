# Phase 19 — Brand System

Status: **COMPLETE**

## Delivered scope

- Immutable `brand-strategist@1`, an R0 `manual_advisory_only` contract with no
  tools or assigned skills.
- Required pinning of the exact current founder-approved strategy and active
  founder-approved product/offer portfolio derived from that strategy.
- Complete proposed artifacts for brand strategy, positioning, naming analysis,
  voice, messaging, tagline, visual direction, brand rules, and asset references.
- Exact dual-source citations on every artifact, globally unique identifiers, and
  runtime semantic validation against complete pinned allowlists.
- Protected `/brand` API and UI with optimistic version checking and a separate
  CSRF-protected founder approval action.
- Immutable selected-business brand-system versions with one active version and
  preserved superseded history.
- Active approved brand retrieval through the Business Brain `brand` source,
  including directly reusable `brand_rules`.
- Transactional `brand.approved` events with durable audit delivery.

## Evidence and approval boundary

The agent cannot run until the selected business has both a current approved
strategy and an active approved product/offer portfolio derived from it. The run
input pins both approvals' versions, source runs, contexts, payloads, and every
eligible item reference. The runtime rejects invented citations, duplicate item
identifiers, missing artifacts, self-approved statuses, availability claims, and
asset-creation claims.

Agent output always has `brand_status: proposed`. Only the authenticated founder
can approve a completed, revalidated run tied to the still-current strategy and
offer portfolio. Approval creates a new active brand-system version and preserves
the previous version as superseded. This founder-approved record is the sole brand
authority exposed to future consumers through the Business Brain.

## Provider and phase boundary

The agent uses the existing provider-independent model gateway. Phase 19 adds no
model-specific, creative, design, domain, trademark, hosting, deployment, or
publishing provider. It cannot generate asset files, register names, build a
website, publish content, spend, contact people, or create tasks and workflows.

Phase 20 website specification implementation is not included. Phase 19 stops
after making the active approved brand system and its rules available as
structured, traceable business data.

## Acceptance evidence

Migration `20260825_19` creates the immutable brand-system table, active-row
constraint, and Brand Strategist. The deterministic suite includes 139 API tests
and both web tests, strict Python and TypeScript checks, production builds,
migration round-trip verification, contract/CSRF/protected-UI smoke coverage, and
five healthy primary Docker services. No model-provider call is needed for the
Phase 19 deterministic gate; model use occurs only when the founder explicitly
queues a valid Brand Strategist run.
