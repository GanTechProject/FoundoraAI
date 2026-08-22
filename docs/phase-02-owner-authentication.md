# Phase 02 — Owner Authentication & Security Base

Status date: 2026-08-22

## Scope delivered

- exactly one server-provisioned owner account and no public signup;
- 15–128 character passwords hashed with Argon2id;
- cryptographically random, opaque, database-backed sessions with idle and absolute expiry;
- login, logout, password change, current-session inspection, active-session listing, and revoke-other-session APIs;
- public login UI and authenticated owner security settings;
- protected API and web routes;
- exact-origin checks and session-bound CSRF protection for mutations;
- Redis-backed account and network login throttling that fails closed;
- CSP, frame, MIME-sniffing, referrer, permissions, and production HSTS headers;
- production configuration validation requiring HTTPS and secure cookies;
- documented interactive provisioning and explicit credential recovery;
- migration `20260822_02` for `owners` and `owner_sessions`.

## Security invariants

- Foundora creates no default owner or password.
- Passwords and raw session/CSRF tokens are not stored in PostgreSQL, logs, committed files, or browser bundles.
- Login failure responses do not reveal whether an owner email exists.
- A password change verifies the current password, revokes every prior session, and rotates the current browser to a new session.
- Missing Redis makes login temporarily unavailable rather than bypassing throttling.
- Health endpoints are deliberately unauthenticated for Compose orchestration; product and settings data is not exposed there.
- Production mode cannot start with an HTTP public origin or an insecure cookie configuration.

## Acceptance evidence

The reproducible gates are `./scripts/quality.ps1`, `./scripts/smoke.ps1`, and the combined `./scripts/verify.ps1`. The smoke suite creates an isolated temporary PostgreSQL database, Redis database, API container, and web container; provisions a random credential in memory; proves unauthenticated requests are rejected; logs in through the real web form; exercises password rotation, throttling, and logout; verifies old-session revocation and CSRF rejection; renders authenticated settings; and checks migration state and security headers. Temporary resources are removed in a `finally` block, so verification cannot replace a development owner's credentials. The primary Compose application remains running.

No Phase 03 business-workspace tables or behavior were introduced.
