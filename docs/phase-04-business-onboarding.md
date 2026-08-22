# Phase 04 — Business Onboarding

Status date: 2026-08-22

## Scope delivered

- protected selected-business onboarding at `/onboarding`;
- resumable foundation, market, execution, and brand/services input steps;
- idea or existing-business classification, name, industry, geography, problem, target audience, offer, goals, existing assets, constraints, budget context, brand preferences, and declared services;
- revision-checked saves that reject stale concurrent updates;
- completeness validation before a draft can enter frozen review;
- separate submit, approve, return-to-editing, and revise-approved-profile actions;
- versioned founder-approved profiles with approver and approval timestamp;
- migration `20260822_04` for onboarding drafts and approved profiles.

No Phase 05 model gateway, provider adapter, generated interpretation, credential, or fabricated connection state was introduced.

## Fact and isolation invariants

- Onboarding endpoints never accept a business ID. Every read and mutation uses the Phase 03 selected-business resolver and rechecks both session owner and active business.
- A saved draft is resumable but unapproved. No approved profile row exists until the founder separately approves a complete frozen review.
- Review drafts cannot be mutated. Stale revision writes return conflict.
- Reopening an approved profile preserves the last approved version unchanged while edits remain in draft.
- Reapproval replaces the approved facts only after another review and increments the version.
- Approved values are copied exactly from the reviewed founder input; no inferred fields are inserted.
- Declared services are context strings only and never produce connected-provider state.

## Acceptance evidence

`./scripts/verify.ps1` runs formatting, lint, strict Python and TypeScript type checking, unit tests, production builds, migrations, health checks, and an isolated Docker smoke suite. The Phase 04 smoke path saves each API step, resumes the persisted draft, rejects a stale revision, rejects an incomplete submission, rejects approval before review, freezes review against edits, records exact approval version one, proves an unapproved revision cannot change it, and records exact reapproval version two. It switches to another business and proves no onboarding draft or approved profile crosses the boundary. It also submits the real Next.js foundation form and verifies the wizard resumes at the market step.

PostgreSQL evidence verifies migration `20260822_04`, two isolated drafts, exactly one approved profile at version two, and its exact approved offer. Temporary API, web, PostgreSQL database, and Redis state are removed in a `finally` block; the primary owner and business data remain untouched.

No Phase 05 behavior is implemented.
