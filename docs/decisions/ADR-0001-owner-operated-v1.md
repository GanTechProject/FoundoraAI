# ADR-0001: Owner-operated V1 with future SaaS boundaries

- Status: Accepted
- Date: 2026-08-22

## Context

Foundora must become useful to one founder launching and operating real businesses before investing in public SaaS scale.

## Decision

Build V1 for one owner account that can manage multiple businesses. Do not implement organizations, tenants, subscriptions, public signup, team RBAC, enterprise SSO, per-tenant billing/secrets/quotas, Kubernetes, or multi-region infrastructure. Keep core agent, skill, workflow, task, governance, provider, knowledge, memory, and business modules independent of the owner-authentication shell.

## Consequences

Delivery focuses on verified business capability. Records are scoped to a business where relevant, but `business_id` is not treated as a future security tenant boundary. SaaS conversion will require an explicit organization/tenant layer later.
