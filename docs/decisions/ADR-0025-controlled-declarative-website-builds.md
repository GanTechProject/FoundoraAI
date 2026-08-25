# ADR-0025: Controlled declarative website builds before sandbox execution

Status: Accepted

Date: 2026-08-25

## Context

Phase 21 must generate and modify a real website project, manage dependencies, and
prove build and quality results. A model-authored statement that a build passed is
not evidence. At the same time, Phase 22—not Phase 21—owns isolated execution of
generated code with CPU, memory, process, timeout, filesystem, network, credential,
and cleanup controls.

## Decision

Seed `website-coding@1` as an immutable R1 agent with exactly one assigned
`website-build@1` skill. A run requires the exact current founder-approved website
specification. A modification additionally pins the current project ID, version,
source tree, dependency manifest, and source/build digests.

The model may return only a bounded declarative change set, an empty reviewed
dependency manifest, complete specification-to-file traceability, and page tests.
It cannot return build or check status. The runtime permits only four code-reviewed
internal capabilities: controlled repository, controlled temporary filesystem,
reviewed dependency resolution, and deterministic website checks.

The controlled builder rejects absolute, hidden, traversal, executable, oversized,
remote-network, dynamic-network JavaScript, and credential-shaped content. It
applies add/update/delete operations to a temporary source tree, materializes a
separate build tree without executing generated code, hashes both trees, and checks
page coverage, generated assertions, internal links, structural lint, core
accessibility, technical SEO, and byte budgets. Any failure rejects the project.

Only a successful computed result creates an immutable active project version,
supersedes the former active version, and publishes `website_project.built` in the
same transaction as the agent completion. The Business Brain receives bounded build
metadata, not the source tree, and excludes stale project metadata when the approved
specification changes.

## Consequences

- Project generation and modification use controlled capabilities instead of raw
  host repository or filesystem access.
- Build success is supported by concrete materialized files, hashes, and computed
  checks rather than model testimony.
- The reviewed dependency allowlist is empty in Phase 21, so package installation,
  lifecycle scripts, and transitive supply-chain execution cannot occur.
- Static HTML, CSS, JavaScript, JSON, and text remain provider-neutral; no framework,
  CMS, host, deployment service, analytics service, or domain provider is selected.
- General generated-code execution, resource isolation, preview execution, and
  cleanup controls remain Phase 22 work. Deployment remains Phase 24 work.

## Supersession

This decision extends ADR-0004, ADR-0012, ADR-0013, ADR-0016, ADR-0017, and
ADR-0024. It does not supersede them.
