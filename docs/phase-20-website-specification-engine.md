# Phase 20 — Website Specification Engine

Status: **COMPLETE**

## Delivered scope

- Immutable `website-specification@1`, an R0 `manual_advisory_only` contract with
  no tools, skills, repository access, or filesystem access.
- Required pinning of the exact aligned current founder-approved strategy, active
  product/offer portfolio, and active brand system.
- Complete structured site objective, rooted sitemap, page specifications,
  conversion goals, SEO requirements, content requirements, brand constraints,
  and provider-neutral technical requirements.
- Exact three-source citations for every top-level artifact, globally unique
  requirement identifiers, resolved page targets, an acyclic page hierarchy, and
  exactly one page specification per sitemap page.
- Protected `/website-specifications` API and UI with optimistic version checking
  and a separate CSRF-protected founder approval action.
- Immutable selected-business versions with one active version and preserved
  superseded history.
- Active approved specification retrieval through the Business Brain, with stale
  exclusion if its strategy, offer, or brand lineage changes.
- Transactional `website_specification.approved` events with durable audit delivery.

## Evidence and approval boundary

The agent cannot run until all three aligned founder approvals exist. Its input
pins their IDs, versions, source runs, contexts, full payloads, and every eligible
item reference. The runtime rejects invented evidence, missing artifacts, duplicate
identifiers, invalid sitemap trees, incomplete page coverage, unresolved conversion
references, unknown page targets, self-approved status, and any claim that code
generation started.

Only the authenticated founder can approve a completed, revalidated run tied to
the still-current strategy, offer, and brand. Approval creates a new active version
and preserves the previous version as superseded. This record is the sole approved
website-specification authority exposed to later consumers.

## Provider and phase boundary

The agent uses the existing provider-independent model gateway. Phase 20 adds no
framework, repository, filesystem, CMS, analytics, hosting, deployment, domain,
creative, or publishing provider. Technical requirements describe outcomes and
acceptance criteria without selecting a vendor.

Phase 21 website/coding-agent implementation is not included. The contract records
`code_generation_status: not_started`; it cannot generate or edit source, manage
dependencies, run builds or tests, or claim a website exists.

## Acceptance evidence

Migration `20260825_20` creates the immutable specification-version table,
active-row constraint, and Website Specification Agent. The deterministic suite
includes 143 API tests and both web tests, strict Python and TypeScript checks,
production builds, migration round-trip verification, contract/CSRF/protected-UI
smoke coverage, and five healthy primary Docker services. No model-provider call
is needed for the Phase 20 deterministic gate; model use occurs only when the
founder explicitly queues a valid Website Specification Agent run.
