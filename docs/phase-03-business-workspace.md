# Phase 03 — Business Workspace

Status date: 2026-08-22

## Scope delivered

- create and list multiple businesses owned by the single founder;
- explicit per-session business switching with no global cross-session side effect;
- selected-business profile editing with a name and concise summary;
- lifecycle status values `planning`, `active`, and `paused`;
- durable archive behavior that prevents reselection and clears stale session selections;
- validated IANA timezone, three-letter currency, and BCP 47 locale preferences;
- selected-business goals with target dates and active, completed, or cancelled status;
- protected server-rendered business workspace and owner navigation;
- migration `20260822_03` for businesses, preferences, goals, and session selection.

Phase 04 onboarding fields were deliberately not introduced.

## Isolation invariants

- Only `/businesses/select` accepts a business ID for context selection.
- Every operational service query joins the authenticated session's selection to a non-archived business and verifies the owner on both records.
- Goal changes also filter by the selected business's ID, so possessing a goal UUID from another business is insufficient.
- Creating another business leaves an existing selection unchanged.
- Business selection is per session; independent sessions can operate in different business contexts.
- Archiving clears matching selections in all owner sessions in the same transaction.
- Preferences and goals have non-null business foreign keys and cascade only with their owning business.

## Acceptance evidence

`./scripts/verify.ps1` runs formatting, lint, strict Python and TypeScript type checking, unit tests, production builds, migrations, health checks, and an isolated Docker smoke suite. The smoke suite creates two API-driven businesses plus one through the real Next.js server action. It creates distinct goals in the first two businesses, switches repeatedly, proves neither profile nor goals cross the boundary, rejects a goal update from the wrong selected context, verifies archive invalidation, and proves two owner sessions retain independent selections. It also verifies migration `20260822_03` and relational persistence directly in PostgreSQL.

Temporary PostgreSQL, Redis, API, and web resources are removed in a `finally` block. The primary development owner and businesses are not modified.

No Phase 04 behavior is implemented.
