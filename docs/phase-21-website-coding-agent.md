# Phase 21 — Website/Coding Agent

Status: **COMPLETE**

## Delivered scope

- Immutable `website-coding@1` R1 contract with exactly assigned
  `website-build@1` skill and four code-reviewed internal tool identifiers.
- Exact current founder-approved website-specification pinning before generation,
  plus exact current source tree and digest pinning before modification.
- Complete declarative add/update/delete source changes for bounded HTML, CSS,
  JavaScript, JSON, and text files.
- Complete traceability from every approved objective, sitemap page, page section,
  conversion goal, SEO requirement, content requirement, brand constraint, and
  technical requirement to resulting files.
- Reviewed dependency management with an empty allowlist and no package execution.
- A controlled temporary repository/filesystem builder that materializes a distinct
  build tree without running generated code.
- Computed page tests, internal-link and structural lint, accessibility checks,
  technical SEO checks, byte-budget performance checks, and source/build hashes.
- Immutable active/superseded selected-business project versions, transactional
  `website_project.built` events, protected API/UI, and bounded Business Brain build
  metadata with stale-specification exclusion.

## Build truth and failure boundary

The model cannot include build or quality status in its schema. It supplies proposed
source changes and tests only. Runtime semantic validation rejects incomplete
specification coverage, unsafe or duplicate paths, invalid add/update/delete
semantics, stale modification bases, and nonempty dependency manifests. The
controlled builder then performs the file writes and computes every result.

No project row is created if a sitemap page is absent, a generated assertion fails,
an internal link is broken, required page structure or metadata is absent, CSS or
JavaScript structure fails lint, byte limits are exceeded, content references a
network resource, credential material is detected, governance disables a required
tool, or the specification/base changes before commit. A successful project records
the exact source files, per-file hashes, source-tree digest, build manifest,
build-tree digest, check metrics, and ordered tool audit.

## Provider and phase boundary

Phase 21 adds no framework, CMS, package provider, analytics provider, hosting
provider, deployment provider, or domain provider. Its source profile is portable
static web technology. The dependency allowlist is deliberately empty.

The builder does not execute generated JavaScript, commands, subprocesses, package
installers, or lifecycle scripts. Phase 22 must add and verify the sandbox resource,
network, credential, timeout, process, filesystem, and cleanup controls before any
generated-code execution is authorized. Phase 23 visual/website QA, Phase 24
deployment, and Phase 25 domain/DNS work are not included.

## Acceptance evidence

Migration `20260825_21` creates the immutable project-version table, its single-active
constraint, the Website/Coding Agent, the controlled Website Build Skill, and their
exact-version assignment. The migration was verified by fresh upgrade, downgrade to
`20260825_20`, and re-upgrade to `20260825_21` in an isolated database.

The deterministic suite includes 148 API tests and both web tests, strict Python and
TypeScript checks, a production web build, contract/CSRF/protected-UI smoke coverage,
and a real controlled-builder smoke probe that materializes and hashes a passing site.
No model-provider call is needed for the Phase 21 deterministic gate; a provider is
used only when the founder explicitly queues a valid coding run.
