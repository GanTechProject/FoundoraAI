# ADR-0008: Session-selected business context and strict operational scoping

## Status

Accepted on 2026-08-22.

## Context

Foundora is owner-operated but must manage multiple founder-owned businesses. A single global selection would make concurrent browser sessions interfere with one another, while client-supplied `business_id` values on every operational request would create a recurring cross-business data exposure risk. The business boundary is not a SaaS tenant or organization boundary.

## Decision

- Each authenticated owner session has a nullable `selected_business_id`. The first created business is selected only when that session has no current selection; additional creation does not silently switch context.
- An explicit switch command is the only operational endpoint that accepts a business ID. It verifies that the business belongs to the authenticated owner and is not archived before binding it to the current session.
- Profile, status, preferences, goals, and archive operations resolve the business by joining the authenticated session selection to an active business and checking owner identity on both records. Goal updates additionally require the goal's `business_id` to match that resolved business.
- Archive is a durable timestamp, not deletion. An archived business cannot be selected, and archiving clears that business from every owner session to invalidate stale context immediately.
- Business names are unique per owner without regard to case. Preferences and goals use database foreign keys with cascade behavior; PostgreSQL remains durable truth.
- Sessions remain independent: switching one browser session does not switch another.

## Consequences

Every current and future operational table must contain a non-null business foreign key and be accessed through the same selected-context boundary. The UI cannot accidentally authorize access by changing a hidden business ID. A future SaaS tenant boundary may wrap this model but must not reinterpret `business_id` as tenant identity. Business restoration, deletion, onboarding details, teams, and organizations are outside Phase 03.
