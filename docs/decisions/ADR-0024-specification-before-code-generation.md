# ADR-0024: Founder-approved website specification before code generation

Status: Accepted

Date: 2026-08-25

## Context

Phase 20 must prevent a later coding agent from starting with only a vague prompt.
A useful implementation handoff needs a site objective, information architecture,
page-level direction, conversion goals, SEO and content requirements, brand
constraints, and testable technical requirements. These decisions must remain
traceable to founder-approved business direction and must not be confused with an
implemented website.

## Decision

Seed `website-specification@1` as an immutable R0, manual-advisory-only contract.
A run requires the exact current approved strategy, active approved product/offer
portfolio, and active approved brand system, all aligned to the same strategy and
offer lineage. The run pins their versions, source runs, contexts, full payloads,
and complete item-reference allowlists. Every specification artifact cites exact
items from all three approvals.

The output must include one rooted acyclic sitemap, exactly one complete page
specification per sitemap page, resolved conversion references, and page-targeted
SEO, content, brand, and provider-neutral technical requirements. It always records
`specification_status: proposed` and `code_generation_status: not_started`.

Keep generation separate from a CSRF-protected founder approval. Approval
revalidates all schemas, semantic relationships, evidence, and source freshness;
then it creates an immutable active version, supersedes the former active version,
and publishes `website_specification.approved` transactionally. The active aligned
version enters the Business Brain with founder-approved authority. If its source
approvals later change, Business Brain marks it stale and excludes its payload.

## Consequences

- A future coding agent can require one complete approved specification instead of
  interpreting a vague one-line prompt as implementation authority.
- The specification agent cannot access a repository or filesystem, generate code,
  choose providers, install dependencies, build, deploy, or publish.
- Historical specifications remain inspectable and their exact source lineage is
  preserved.
- The schema is provider-neutral and does not prematurely select a framework, CMS,
  analytics product, host, deployment service, or domain provider.

## Supersession

This decision extends ADR-0011, ADR-0012, ADR-0017, ADR-0021, ADR-0022, and
ADR-0023. It does not supersede them.
