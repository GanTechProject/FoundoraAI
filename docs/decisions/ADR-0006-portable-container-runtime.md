# ADR-0006: Portable container runtime and deferred deployment provider

- Status: Accepted
- Date: 2026-08-22

## Context

Phase 01 depends on PostgreSQL, Redis, an API, a web process, and a worker. The eventual deployment provider is not selected.

## Decision

Require Docker Desktop with Docker Compose for local development. Package the web, API, migrations, and worker as Linux containers, configured through environment variables and standard network endpoints. Keep the core application independent of hosting, cloud, database, cache, and deployment vendors.

## Consequences

Phase 01 acceptance requires real Compose verification. Docker unavailability makes the phase partial or blocked; local host services are not an implicit substitute. Provider selection and production mapping remain deferred to Phase 59.
