# Phase 12 — Event Bus

Status: complete and verified on 2026-08-25.

## Implemented boundary

Phase 12 adds a provider-neutral internal domain-event layer:

- immutable UUID event envelopes with UTC occurrence/creation timestamps;
- code-reviewed event type, schema version, aggregate, and JSON payload contracts;
- producer idempotency plus optional correlation and causation identity;
- a transactional PostgreSQL outbox written with the aggregate mutation;
- one durable delivery per registered consumer;
- atomic handler effect/completion commits and completed-delivery replay refusal;
- worker reconciliation using locked, skip-locked PostgreSQL claims;
- bounded handler timeouts, exponential retry, and sanitized failure evidence;
- durable dead-letter exhaustion and selected-business optimistic redrive;
- protected API and server-rendered `/events` contract/delivery ledger.

The implemented producers are:

- `business.created` from workspace creation;
- `goal.created` from selected-business goal creation;
- `task.completed` and `task.failed` from terminal task transitions;
- `approval.requested` from the governance approval boundary.

Future examples such as `website.deployed`, `lead.created`,
`campaign.completed`, and `metric.anomaly_detected` are not emitted because their
owning domains do not exist yet.

## Delivery semantics

The bus is durable at PostgreSQL, not Redis. Every event and its initial consumer
delivery rows commit with the domain mutation. A worker transaction locks one
available delivery, invokes its registered handler, and commits handler effects
with the completion marker. If the process is interrupted, the transaction rolls
back and the pending delivery remains recoverable.

This yields effectively-once database effects while retaining an at-least-once
recovery model. The unique event/consumer row is the consumer idempotency boundary.
Completed deliveries are not selected again.

Failures persist only the handler exception type and a sanitized message. Attempts
use bounded exponential backoff and enter `dead_letter` after the contract's
maximum. Owner redrive resets the attempt window only from that terminal state;
stale revision or cross-business requests are rejected.

## Persistence

Migration `20260825_12` adds:

- `domain_events` for immutable versioned envelopes;
- `event_deliveries` for consumer attempts, results, retry availability,
  dead-letter evidence, and redrive count.

Existing aggregate-local task/workflow histories and governance audit rows remain
their owning domains' evidence; Phase 12 publishes separate integration events and
does not rewrite prior history.

## Acceptance evidence

The deterministic quality gate passed:

- Ruff format and lint;
- mypy for all 61 API source files;
- all 90 API tests;
- web formatting, lint, and TypeScript checks;
- both web tests;
- the Next.js production build, including `/events`.

The isolated Docker/PostgreSQL smoke suite passed and proved:

- a fresh database migrates through `20260825_12`;
- unauthenticated event access is rejected;
- business, goal, terminal task, and approval mutations publish their required
  event exactly once with the domain transaction;
- the registered audit consumer completes each delivery once, and a second
  dispatcher pass does not increase attempts;
- a missing handler is retried/exhausted into a sanitized durable dead letter;
- explicit redrive works once, stale redrive is rejected, and the failed delivery
  returns honestly to dead letter when its handler is still unavailable;
- event reads and redrive cannot cross the selected-business boundary;
- the protected event ledger renders only real contracts and persisted state;
- API, web, PostgreSQL, Redis, and worker remain healthy.

No model or external provider call is added or required by Phase 12.

## Deferred

Phase 13 knowledge ingestion, external brokers, webhooks, unimplemented-domain
events, external tool/provider consumers, scheduler behavior, and SaaS tenant
controls are not implemented.
