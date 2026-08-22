# ADR-0007: Single-owner password authentication with opaque sessions

## Status

Accepted on 2026-08-22.

## Context

Phase 02 requires secure owner authentication without implementing public SaaS signup, organizations, subscriptions, or provider-specific identity architecture. Passkeys and external identity would introduce recovery, device, provider, and deployment decisions that have not been selected. A self-contained owner credential provides a portable baseline and must remain replaceable later.

## Decision

- Foundora has exactly one owner row, enforced by a database uniqueness constraint. The account is provisioned or intentionally recovered through a server-side interactive command; there is no default credential or public registration.
- Passwords are 15–128 characters without composition rules and are hashed with pwdlib's Argon2id implementation. Plaintext passwords are never persisted or logged.
- Authentication issues a 256-bit random opaque session token and a separate CSRF token. Only their SHA-256 digests are stored in PostgreSQL; tokens contain no identity or authorization data.
- Session cookies are `HttpOnly`, `SameSite=Strict`, path-scoped to `/`, and `Secure` in HTTPS environments. Sessions have a 30-minute idle timeout, an eight-hour absolute timeout, server-side revocation, and rotation after password changes.
- Unsafe API requests require an exact configured origin. Authenticated mutations also require a session-bound CSRF token. Login attempts are throttled in Redis by account and network address and fail closed if the limiter is unavailable.
- Health checks remain public. The login route is public. Owner session and settings routes are protected. Unauthenticated API requests receive `401`; unauthenticated web requests are redirected to login.

## Consequences

The authentication core remains provider-independent and sessions can be revoked immediately. Future passkey or external-identity adapters may be added without changing owner identity or business-domain ownership. MFA, public account recovery, teams, RBAC, organizations, and subscription behavior are not part of Phase 02.
