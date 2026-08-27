# Phase 22 — Sandbox

Status: **COMPLETE — SLICES 0–6 VERIFIED**

Decision: [ADR-0026](decisions/ADR-0026-isolated-generated-code-execution.md)

Plan: [Phase 22 implementation plan](phase-22-sandbox-implementation-plan.md)

## Delivered in Slice 0

- Strict, frozen, extra-field-forbidden `static-website@1` profile, execute-request,
  harness-result, runner-result, effective-limit, route-result, and cleanup-evidence
  contracts.
- Deterministic canonical JSON and SHA-256 request pinning, normalized route limits,
  bounded error/output fields, and truthfulness rules that reject successful results
  without passing routes and verified zero-resource cleanup.
- A dedicated static website runtime derived from Playwright 1.62.0 Noble and pinned
  to OCI digest
  `sha256:baed2032d533817f3dbe6425de795788430ba345e819a1201337009ba17c9d07`.
- Exact Playwright/npm lock data, non-root `pwuser`, fixed Node entrypoint, immutable
  runtime manifest, and no command or image selection surface.
- A fixed loopback-only harness that loads strict route input, safely serves the
  Phase 21 file types, blocks non-loopback browser requests, keeps Chromium's own
  sandbox enabled, executes page JavaScript, captures bounded runtime errors, and
  reports computed JSON rather than accepting model claims.
- The version-matched official Playwright seccomp allowlist, pinned at SHA-256
  `17e2d449ab7c2c6fefc5b9f978224a49929864eb1d5a42f4f9002266c9300de2`.
- CPU, memory, process, JavaScript-error, filesystem, network, environment, output,
  timeout, passing, and malformed-input fixtures.
- Reproducible `scripts/test-sandbox-runtime.ps1` build, image-inspection,
  dependency-audit, browser-probe, negative-probe, and leftover-container gate,
  integrated into the repository quality script.

## Evidence-driven profile corrections

The first pinned-image build exposed that the official Playwright image contains
Node 24.18.0, not the repository web image's Node 24.19.0. The runtime manifest now
records the actual image version, while its package compatibility range accepts the
reviewed Node 24 release line. The build no longer emits an engine mismatch.

A real non-root browser probe also proved that Docker's default seccomp policy
blocks Chromium's required user-namespace calls. Vendoring Playwright's exact
versioned fail-closed profile resolved that without disabling the browser sandbox.
Dropping all Linux capabilities still failed; restoring only namespaced
`SYS_CHROOT` passed with `no-new-privileges`, read-only rootfs, network none, fixed
tmpfs, and all resource ceilings present. `SYS_ADMIN` and every other default
capability remain absent. ADR-0026 and the profile contract record this narrow
exception.

## Delivered in Slice 1

- Migration head `20260827_22` adds ORM-aligned `sandbox_profiles` and
  `sandbox_executions` tables with exact project/specification, artifact digest,
  profile, request, governance action, and policy-version pinning.
- `static-website@1` is seeded with the reviewed Slice 0 limits and security
  controls. A database trigger rejects updates and deletes; profile evolution must
  insert a new version.
- Execution rows enforce selected-business idempotency, legal states, bounded
  recovery/cleanup counters, profile referential integrity, and truthful-success
  cleanup constraints.
- The domain service locks the selected business, returns an existing idempotent
  request, requires the current active project and specification, rejects stale
  source relationships and package dependencies, re-hashes every source file and
  both trees, and creates a canonical request digest without caller-controlled
  routes, profile settings, or status.
- Every new request creates a durable `internal.code.execute` action through the
  existing policy engine for `foundora.sandbox.website`. Both catalog entries are
  fixed at R2, and `force_approval=True` requires an explicit owner decision even
  if autonomy settings would otherwise permit lower-risk work.
- Service-owned legal transitions prevent lifecycle skips and cannot mark an
  execution successful without verified cleanup and zero labeled resources.

## Verified evidence

- Runtime image ID from the final local CI build:
  `sha256:06ed21f34551c9aa3ee817c6fa8b033d764c278adc3251596a107e5a04a97f2b`.
- Runtime manifest SHA-256:
  `ab73f13726b30608c83a212d7cf762ee2b74986f535680377560db69286d8601`.
- Four containerized runtime contract/manifest tests passed.
- Fifteen strict Python sandbox contract tests and six Slice 1 domain tests passed.
- The passing fixture returned HTTP 200, document `complete`, no runtime errors,
  and `execution_marker: true`, proving its JavaScript executed.
- JavaScript exceptions, external networking, route timeout, 100,000-message output
  flood, and undeclared input fields were rejected and reported as expected.
- Output evidence stopped at 32 errors and 500 characters per error.
- Every direct probe ran as non-root with one CPU, 512 MiB memory/no extra swap, 128
  PIDs, network none, read-only rootfs/source, bounded tmpfs, drop `ALL` then add only
  `SYS_CHROOT`, `no-new-privileges`, and the pinned seccomp policy.
- Docker `--rm` plus a label query confirmed zero remaining Slice 0 containers.
- Runtime package audit reported zero vulnerabilities.
- A disposable PostgreSQL database passed fresh upgrade, downgrade/re-upgrade,
  immutable-profile mutation rejection, and `alembic check` with no metadata drift.
- Repository-wide quality passed: Python formatting, Ruff, strict mypy, all 174 API
  tests, migration execution, clean `alembic check`, web formatting/lint/typecheck,
  all nine web tests, and production web build.

## Delivered in Slice 2

- A dedicated dependency-free Node runner exposes a strict versioned protocol over
  the internal-only `sandbox-control` network. Bearer authentication is mandatory for
  execute, inspect, cancel, and acknowledge operations; no host port is published.
- The worker is the only application service on the control network. API, web,
  PostgreSQL, and Redis remain unreachable from it, and only the runner receives the
  read-only Docker Engine socket mount.
- Callers provide only canonical, digest-pinned Phase 21 source evidence. Unknown
  fields, image/command/environment/mount/control overrides, malformed routes, stale
  hashes, oversized input, and conflicting idempotent replays fail before child create.
- The runner resolves the reviewed runtime image to an immutable ID, creates each
  child from a fixed configuration, and inspects the resulting engine object before
  start. One CPU, 512 MiB/no extra swap, 128 PIDs, network none, read-only root and
  source, fixed tmpfs, capability drop `ALL` plus only `SYS_CHROOT`, the pinned seccomp
  profile, `no-new-privileges`, no devices/ports/host namespaces, and capped local logs
  must all match.
- Source is staged through a runner-owned labeled Docker volume and a stopped trusted
  helper, then mounted into the generated-code child as read-only subpaths. No host
  source path or application credential is accepted or mounted.
- Atomic fsync-and-rename receipts record request identity, immutable runtime image,
  effective controls, child identity, bounded process evidence, cancellation,
  acknowledgements, cleanup attempts, and the final zero-resource query.
- Deterministic labels, in-flight request coalescing, persisted replay/conflict checks,
  explicit cancellation, timeout enforcement, `finally` cleanup, bounded retries, and
  startup/periodic janitors cover normal and interrupted runner lifecycles.
- The runner and runtime use separate pinned build contexts. The runner itself is
  non-root with a read-only root filesystem, all capabilities dropped,
  `no-new-privileges`, bounded tmpfs, a persistent receipt volume, and a health probe
  that fails closed if the runtime image or engine boundary is unavailable.

## Slice 2 verification

- The runner contract suite passed canonical-envelope, undeclared-field, digest, and
  deterministic source-archive tests.
- Live integration passed successful JavaScript execution, JavaScript failure,
  external-network denial, bounded-output handling, cancellation, matching replay,
  simultaneous matching requests with one child, conflicting replay,
  unauthenticated request, forbidden override, inspect, and acknowledgement probes.
- Every success, failure, cancellation, and rejection path ended with engine queries
  reporting zero labeled child containers and zero labeled source volumes.
- A deliberately orphaned labeled container and volume were removed after runner
  restart, proving startup janitor reconciliation independently of the request path.
- Unit recovery probes verified that an interrupted receipt with no remaining engine
  resource becomes an honest infrastructure failure and that corrupt receipt data
  fails startup reconciliation closed.
- Topology inspection confirmed the runner is attached only to
  `foundora_sandbox-control`, has no application/provider/database/Redis credentials,
  exposes no host port, and is the only service with a Docker socket mount.
- Runner package audit reported zero vulnerabilities. Built image IDs for this gate
  were runtime
  `sha256:fc3c66a81391f0330539895428bd0c5664a228b58958c29ad320dd1441548640`
  and runner
  `sha256:4b7c74559195a2ab92d780ec1585da8b70f05111d9f405e12f7296f84a4506d3`.

## Delivered in Slice 3

- Approved executions now enter the existing RQ queue with a deterministic job ID;
  each bounded recovery generation receives its own deterministic suffix. Queue
  delivery failure remains durable and recoverable rather than fabricating a run.
- A strict authenticated Python runner client validates exact response shapes,
  identity and digest parity, bounded evidence, terminal truthfulness, cleanup proof,
  and missing-execution absence proofs before application state can change.
- The worker locks and reconstructs every pinned request from current immutable
  project/specification evidence, checks the stored policy/action target, and forces
  a live policy, kill-switch, tool-permission, classification, and spend recheck
  immediately before the runner can create a child.
- Runtime orchestration inspects the runner before submission, submits at most once,
  records heartbeat and effective controls, propagates owner cancellation, attaches
  to in-flight receipts after worker restart, and acknowledges receipts only after
  their terminal state is committed.
- Terminal persistence validates receipt identity and makes success contingent on
  runner-verified cleanup with zero remaining labeled resources. A strict absence
  proof is required before a never-launched or lost execution can become cancelled or
  infrastructure-failed.
- Startup and periodic worker maintenance reconcile queued and stale authorizing,
  running, or cleaning rows against runner receipts before any retry. Recovery is
  bounded to three generations and never uses Redis or an RQ result as execution
  truth.
- The trusted runner's missing-execution cancellation now performs an engine query,
  removes any labeled remnants, and returns a durable zero-resource absence proof.

## Slice 3 verification

- Forty-nine focused governance, configuration, sandbox-contract, domain-service,
  strict-client, and orchestration tests passed.
- Worker checkpoint tests covered pre-launch delivery, running and cleanup receipt
  attachment, result-return commit, pre-launch cancellation, and deterministic
  recovery job identity without duplicate runner submission.
- A regression test proved that the global kill switch revokes an already authorized
  action during the worker's forced execution-time recheck.
- Strict mypy reported no issues across 102 API source files; Ruff and formatting
  checks passed for the API source and tests.
- The live runner integration passed the new missing-execution absence-proof path in
  addition to the existing isolation, idempotency, cancellation, adversarial, cleanup,
  restart-janitor, and zero-vulnerability gates.
- Repository-wide deterministic CI passed: Python formatting, Ruff, strict mypy, all
  185 API tests, migration execution, clean `alembic check`, web formatting, lint,
  typecheck, all nine web tests, production build, both live sandbox suites, API
  readiness, worker health, and the rebuilt default stack at migration `20260827_22`.

## Delivered in Slice 4

- Protected selected-business APIs now request an execution, start only an approved
  request, record cancellation intent, list bounded history, and inspect one exact
  execution. Every mutation uses the existing authenticated CSRF boundary and every
  response is explicitly `Cache-Control: no-store`.
- List and detail repository queries resolve the active owner session and constrain
  execution rows by the selected business. A missing or cross-business identifier is
  reported as not found rather than leaking execution evidence.
- Detail responses expose immutable project/specification/profile/policy pins,
  governance and approval state, bounded runner results and excerpts, evidence
  digests, heartbeat/recovery state, and cleanup proof. Raw source archives,
  credentials, runner authentication, and unbounded logs are never returned.
- The `/sandbox` owner page requests a governed execution, links directly to its
  durable approval, exposes start only after approval, supports cancellation, lists
  selected-business history, and displays exact runtime/cleanup evidence.
- Untrusted stdout, stderr, route results, process results, and termination reasons
  are rendered only through React text nodes or JSON serialization. The UI contains
  no raw-markup rendering path.
- Sandbox mutations use an explicit 15-second web-to-API timeout, preserve encoded
  execution identity, generate fresh idempotency keys for requests, and map durable
  conflict, denial, invalid-input, missing, and queue states to truthful owner notices.

## Slice 4 verification

- Focused API tests passed authentication, CSRF, `no-store`, request/start/cancel,
  queue-failure, bounded evidence, safe untrusted-string serialization, and
  selected-business response checks.
- Web tests passed cookie forwarding, `no-store` GETs, five-second read timeouts,
  15-second mutation timeouts, idempotency and encoded-identity handling, and plain
  data handling for malicious runner excerpts.
- Focused checks passed 27 API tests, all 12 web tests, Ruff, formatting, web lint,
  TypeScript, and strict mypy across 103 API source files.
- Repository-wide deterministic CI passed all 190 API tests, all 12 web tests,
  migration upgrade and Alembic drift checks, the production build including
  `/sandbox`, both live sandbox probe suites, and readiness/health checks for the
  default stack at migration `20260827_22`.

## Delivered in Slice 5

- Registered versioned `sandbox.execution.finished` events with the existing audit
  consumer. Terminal state, bounded outcome metadata, immutable project/profile,
  governance and request pins, duration, and cleanup proof enter the PostgreSQL
  transactional outbox in the same commit.
- Event construction rejects nonterminal executions and incomplete cleanup evidence.
  Payloads exclude source archives, stdout/stderr, process output, environments,
  credentials, and runner authentication; deterministic event idempotency prevents
  duplicate delivery under receipt replay.
- Worker JSON logs now expose an allowlisted set of terminal duration/outcome,
  cleanup, remaining-resource, and recovery counters without serializing untrusted
  execution output.
- Runner readiness continues to exercise Docker Engine access and immutable runtime
  image resolution without launching generated code. Its internal response now adds
  bounded process-lifetime metrics for launches, replays, rejected/conflicting
  requests, cancellations, outcomes, cleanup, janitor work, duration, readiness, and
  remaining labeled resources.
- Runner audit logs now distinguish execution replay/conflict, outcome, duration,
  cleanup attempts, remaining resources, and startup/periodic janitor work. The
  health check validates the full readiness shape and rejects malformed telemetry.
- Deterministic recovery tests cover receipt-first terminal reconciliation, exhausted
  worker recovery requiring an engine-backed absence proof, and one exact recovery
  delivery. Live runner probes cover concurrent replay, conflict, cancellation,
  failed executions, cleanup, readiness metrics, and startup janitor convergence.
- `scripts/smoke.ps1` now checks runner readiness and zero managed child containers
  and source volumes before and after its application scenario, and validates the
  current `20260827_22` migration head.
- [Sandbox operations](sandbox-operations.md) documents health, bounded telemetry,
  zero-resource checks, kill-switch use, receipt-preserving recovery, and escalation.

## Slice 5 verification

- Focused checks passed 17 event/runtime/recovery tests, seven runner contract tests,
  Ruff, strict mypy across 103 API source files, and formatting checks.
- Live runner integration passed success/failure/cancellation, matching and
  conflicting replay, simultaneous requests with one child, bounded operational
  metrics, verified cleanup, zero residual resources, runner restart, and startup
  janitor reconciliation. Runner dependency audit reported zero vulnerabilities.
- Repository-wide deterministic CI passed all 196 API tests, all 12 web tests,
  formatting, Ruff, strict mypy, ESLint, TypeScript, migration upgrade and Alembic
  drift checks, the production build including `/sandbox`, both live sandbox suites,
  dependency audits, and readiness/health checks for every default long-running
  service at migration `20260827_22`.

## Delivered and verified in Slice 6

- The live runner acceptance suite now executes two independent passes covering
  successful JavaScript, browser errors, CPU pressure, 512 MiB allocation failure,
  128-PID pressure, external and Compose-network probes, host-file probes, output
  flooding, owner cancellation, unauthorized requests, profile/command overrides,
  replay, conflicting identity, and simultaneous matching requests.
- Every child receipt is checked against the complete `static-website@1` effective
  profile: one CPU, 512 MiB memory and swap, 128 PIDs, 60-second wall watchdog,
  three-second termination grace, 128 MiB `/tmp` and `/dev/shm`, 1 MiB combined
  output, network `none`, read-only root and source, non-root user, capability drop
  `ALL` with only `SYS_CHROOT`, no new privileges, host namespaces, devices, ports,
  host binds, or `SYS_ADMIN`, and the pinned seccomp digest.
- Memory pressure is truthfully classified `resource_exhausted` when Chromium
  reports its bounded allocation failure. CPU pressure terminates under the inner
  route watchdog. A deterministic runner contract probe forces a hung child through
  the fixed wall watchdog and proves stop, `timed_out`, and verified cleanup; values
  above 60 seconds are rejected by construction.
- Contract tests prove malformed runtime JSON, the wall watchdog, interrupted
  receipts, corrupt receipts, and runner restart all fail closed and converge only
  after zero labeled containers and volumes. The live restart drill independently
  removes an orphaned stopped child and source volume.
- API runtime tests cover missing/rejected approval, the global kill switch,
  disabled tool, stale policy and target, and wrong-business evidence. Every denial
  obtains an engine-backed absence proof and calls execute zero times. The live
  suite proves matching concurrent and replayed requests create at most one child.
- Credential names are absent from runner configuration and every durable receipt;
  the child receives only `HOME` and `NODE_ENV`. API events and logs remain bounded
  allowlists without source, environment, provider keys, or runner authentication.
- The runner moved to pinned Node 24.19.0 Alpine digest
  `sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43`,
  upgrades OpenSSL to fixed version 3.5.8-r0, and removes the unused npm CLI tree.
  The runtime removes its unused npm CLI tree and vulnerable GStreamer bad-plugin
  set. Docker Scout then reported zero critical/high findings for both final images;
  both npm package audits also reported zero vulnerabilities.

## Final acceptance evidence

- Commands: `./scripts/test-sandbox-runner.ps1`, `./scripts/ci.ps1`, Docker Scout
  `cves --only-severity critical,high` for both local images, and post-run labeled
  container/volume queries.
- Runner contract tests: 10 passed. Repeated live adversarial passes: two passed.
  Focused governance/runtime/domain tests: 46 passed.
- Repository-wide deterministic CI passed formatting, Ruff, strict mypy across 103
  source files, all 202 API tests, all 12 web tests, Alembic metadata drift, the
  production build including `/sandbox`, both sandbox suites, and readiness/health
  for every default long-running service at migration `20260827_22`.
- A fresh temporary database upgraded from empty to head, downgraded to
  `20260825_21`, re-upgraded through the strategy-profile correction and Phase 22,
  passed `alembic check`, and was removed.
- Final runtime image ID:
  `sha256:92d1cc02ea1d5a5893ba43c35232e9aaa862f1cf1c0b02ebd6266b681763f861`.
- Final runner image ID:
  `sha256:c70dda59088738f6f971f8f66b424c9739e547feb713c3ef11eaf2d383e5e46b`.
- Runtime manifest SHA-256:
  `ab73f13726b30608c83a212d7cf762ee2b74986f535680377560db69286d8601`;
  seccomp SHA-256:
  `17e2d449ab7c2c6fefc5b9f978224a49929864eb1d5a42f4f9002266c9300de2`.
- Final Docker Scout result: runtime 0 critical/0 high; runner 0 critical/0 high.
- Final resource query: zero `foundora.sandbox.managed=true` containers and zero
  volumes after both attack passes and runner restart.

Known limitation: this V1 boundary isolates untrusted generated website code on one
owner-operated Docker host. The narrowly trusted runner still controls the local
Docker socket, so this is not a hostile-kernel, hostile-runner, multi-tenant, or
production fleet isolation boundary. Production infrastructure remains deferred to
Phase 59. Phase 23 was not changed.
