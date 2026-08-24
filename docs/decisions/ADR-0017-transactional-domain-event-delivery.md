# ADR-0017: Transactional domain events with idempotent durable delivery

## Status

Accepted on 2026-08-25.

## Context

Phase 12 requires internal domain events with IDs, timestamps, idempotent
consumers, retry/dead-letter behavior, and predictable registered-handler
execution. Publishing a database mutation and a Redis message as separate writes
would create a dual-write gap. Treating Redis as event truth would also conflict
with Foundora's PostgreSQL durability boundary.

## Decision

- Store immutable, business-scoped event envelopes in PostgreSQL in the same
  transaction as their aggregate mutation. Each envelope carries a UUID, event
  type, schema version, aggregate identity, idempotency key, payload, UTC
  occurrence timestamp, and optional correlation/causation identity.
- Keep a code-reviewed provider-neutral contract registry. Producers cannot emit
  unknown event types, versions, aggregate types, or payload shapes.
- Create one durable delivery row per registered consumer with a unique
  `(event_id, consumer_name)` boundary.
- Run a handler and mark its delivery completed in the same database transaction.
  A crash rolls back both; a completed row is never selected again. Handlers must
  keep their database effects idempotent under the event/consumer identity.
- Let the existing worker reconcile pending deliveries directly from PostgreSQL
  using row locks and `SKIP LOCKED`. Redis remains available for other work queues
  but is not required to retain or recover domain events.
- Bound every handler runtime and retry sanitized failures with exponential backoff. Exhausted
  deliveries become durable dead letters. The authenticated owner may explicitly
  redrive only a dead letter in the selected business, with optimistic redrive
  revision protection.
- Publish only events owned by implemented domains: `business.created`,
  `goal.created`, `task.completed`, `task.failed`, and `approval.requested`.

## Consequences

- A committed domain mutation cannot lose its corresponding event.
- Registered database handlers have effectively-once effects: handler changes and
  completion evidence commit atomically, while the underlying delivery model
  remains safe under at-least-once worker recovery.
- Duplicate producer calls with the same semantic idempotency key return the same
  event; conflicting reuse is rejected.
- Failed delivery evidence is durable, sanitized, selected-business scoped, and
  operator-recoverable without fabricating handler success.
- Phase 13 knowledge ingestion, external brokers, webhooks, provider-specific
  adapters, and events for unimplemented domains remain deferred.
