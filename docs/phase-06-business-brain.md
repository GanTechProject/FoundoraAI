# Phase 06 - Company / Business Brain

Status date: 2026-08-22

## Scope delivered

- a read-only Context Service that assembles model-ready context exclusively for
  the authenticated session's selected business;
- explicit caller selection across live business profile, approved onboarding
  profile, approved goals, products/services, brand, operating context, and
  operational goals;
- a conservative, deterministic token budget of one token per UTF-8 byte, with a
  declared range of 256 to 32,768 and a 4,096 default;
- source-level provenance containing authority, reference, version, timestamp,
  validity, inclusion decision, exclusion reason, token estimate, and content
  hash;
- deterministic context and decision fingerprints for the same business, source
  versions, purpose, selection, and budget;
- explicit exclusion of completed goals as stale and cancelled goals as
  invalidated, with excluded content omitted from the API response;
- honest availability reporting for future strategy, customer, decision,
  knowledge, task, KPI, and memory domains;
- protected `GET /brain/context` and a server-rendered `/brain` builder and
  provenance view.

## Source authority boundary

The service reads only durable, owner-controlled state already authorized by
earlier phases: the live business and preferences, the latest founder-approved
onboarding profile, and business goals. Mutable onboarding drafts are deliberately
not queried. One approved profile is split into focused source records so a caller
can select only the approved facts needed for a purpose without including the
entire profile.

No missing future domain is synthesized from nearby text. It is returned under
`unavailable_sources` with the phase or capability that must introduce it.

## Selection and budgeting

Sources have a fixed, documented priority: business profile, approved profile,
approved goals, products/services, brand, operating context, then operational
goals ordered by most recent update. Invalid, stale, and unselected candidates are
excluded before budgeting. Each remaining candidate is included only when the
complete canonical JSON payload remains within the requested ceiling.

The estimator intentionally counts every UTF-8 byte as one token. Provider
tokenizers normally produce fewer tokens, so this is conservative and independent
of any provider. Later model callers must still apply the model gateway's total
operation budget to context plus instructions and output.

## Persistence decision

Phase 06 adds no table and no migration. Context is a derived snapshot of existing
authoritative records; persisting another mutable copy would create an avoidable
staleness boundary. Provenance versions and SHA-256 fingerprints make a generated
payload inspectable and reproducible without duplicating it. The current schema
head remains `20260822_05`.

## Acceptance evidence

`./scripts/verify.ps1` runs formatting, linting, strict type checking, backend and
frontend tests, production build, Compose validation, migrations, service health,
and an isolated end-to-end smoke suite. The Phase 06 checks prove that:

- unauthenticated access is rejected and the session-selected business is the
  only business represented;
- revised founder-approved content is used while draft and cross-business content
  remain absent;
- completed and cancelled goals retain provenance but cannot enter compiled
  context;
- source selection and a 256-token ceiling are enforced;
- unavailable future sources are disclosed and the protected `/brain` view is
  backed by real API state.

Phase 07 now consumes this service only through an explicit, bounded,
selected-business snapshot; the Phase 06 provenance and approval boundaries remain
unchanged.
