# Reliability review fixes

Status: implemented on 2026-08-23 after the Phase 09 top-to-bottom review.

The review corrections preserve the Phase 09 product boundary while closing six
cross-cutting reliability gaps:

- push and pull-request CI is deterministic and never requires or bills model
  provider credentials; live-provider acceptance is an explicit manual job;
- the RQ worker reconciles missing durable queue delivery and reclaims a run left
  `running` beyond its job timeout, with at most three worker recoveries;
- model gateway structured responses are validated against the complete supplied
  JSON Schema before success is recorded;
- client-cancelled streams retain a sanitized failed attempt record, protected by
  operation-attempt uniqueness;
- session activity refreshes at half the configured idle timeout, capped at five
  minutes, so short supported idle timeouts remain usable;
- task dashboards use bounded pagination and bulk owner/dependency loading, while
  full event history remains available from the individual task inspector.

Migration `20260823_09` adds the bounded agent-run recovery counter and model
operation-attempt uniqueness. No provider-specific deployment architecture or
new product phase was introduced.

Final verification evidence:

- all 71 API tests and both web tests pass;
- API and web formatting, lint, type checking, and production builds pass;
- a fresh PostgreSQL database upgrades through every migration to
  `20260823_09`;
- API, web, PostgreSQL, Redis, and the worker are healthy under Docker Compose;
- live provider calls remain opt-in and were not billed by this deterministic
  review gate.
