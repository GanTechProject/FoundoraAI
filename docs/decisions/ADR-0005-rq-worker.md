# ADR-0005: Redis Queue for the foundation worker

- Status: Accepted
- Date: 2026-08-22

## Context

Phase 01 requires a separately runnable, Redis-backed worker while schedulers, domain jobs, autonomous workflows, and provider actions belong to later phases. The queue must support durable Redis queues, retries, worker registration/heartbeats, and independent process operation without introducing a distributed platform.

## Decision

Use RQ 2.11.0 with redis-py 8.1.0 for the foundation worker. Run it as a dedicated container against the `foundora` queue. Health checks verify a live registered worker rather than merely checking Redis. Business jobs will be introduced only in their authorized phases and must provide their own idempotency and retry policy.

## Consequences

The local runtime has a small, observable worker process and no scheduler behavior hidden inside it. RQ is an infrastructure adapter; domain code must not depend directly on RQ types. A later replacement remains possible behind the queue boundary if measured requirements justify it.
