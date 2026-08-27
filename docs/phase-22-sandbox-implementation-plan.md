# Phase 22 — Sandbox Implementation Plan

Status: **IMPLEMENTED — SLICES 0–6 VERIFIED**

Decision: [ADR-0026](decisions/ADR-0026-isolated-generated-code-execution.md)

Evidence: [Phase 22 sandbox delivery](phase-22-sandbox.md)

## Outcome

Phase 22 is complete only when Foundora can execute the exact immutable Phase 21
static website in a disposable isolated container, persist honest runtime evidence,
and prove that resource, timeout, process, filesystem, network, credential, and
cleanup controls are effective. No generated code may run in the API, worker,
runner process, host shell, or a container with application authority.

This plan intentionally stops at execution isolation. It does not implement the
Phase 23 Website QA Agent, a public preview, deployment, domains, arbitrary package
dependencies, or a general-purpose build service.

## Security invariants

The implementation must preserve all of these invariants:

1. API and worker containers never receive Docker Engine access.
2. Generated children never receive the Docker socket, runner credential,
   application credentials, host paths, sibling-container access, or published
   ports.
3. A caller cannot select or override an image, command, entrypoint, environment,
   mount, network, capability, device, namespace, or resource ceiling.
4. The source is reconstructed from one exact `WebsiteProjectVersion`, revalidated
   against its stored digests, copied into the stopped child, rehashed, and made
   read-only before execution.
5. Only a code-reviewed, immutable profile and runtime image ID can run.
6. The durable governance action pins the business, project, digests, profile, and
   request digest; authorization is rechecked immediately before launch.
7. A retry for one execution ID is idempotent. It must reattach to or return the
   existing runner receipt, never launch a second child with different content.
8. Every path, including timeout, resource exhaustion, worker interruption, runner
   restart, malformed result, and cancellation, reaches cleanup reconciliation.
9. `succeeded` means execution passed and cleanup was positively verified. Unknown
   cleanup state is failure.
10. Phase 22 stores runtime facts only; it does not claim Phase 23 QA success.

## Initial supported contract

`static-website@1` is the only profile. It accepts the bounded, dependency-free file
types already allowed by Phase 21. The trusted harness starts a loopback static
server and a sandboxed headless browser, loads every approved sitemap route, waits
for a fixed bounded readiness condition, and records:

- route load status and browser/runtime errors;
- child exit code and termination reason;
- wall duration and effective CPU, memory, process, filesystem, and network
  settings;
- peak memory and process count when available from the engine;
- bounded stdout/stderr excerpts and their full-stream hashes; and
- cleanup start/end time plus the final labeled-resource count.

The browser may use loopback inside the child. The child has `network=none`, so it
cannot reach DNS, the Internet, the Compose network, the runner, or application
services. A route that requires an external resource fails honestly.

Profile `static-website@1` starts with one CPU, 512 MiB memory/no extra swap, 128
processes, 60 seconds wall time, bounded termination grace, 128 MiB `/tmp`, 128 MiB
`/dev/shm`, and 1 MiB combined process-output evidence. These values are constants
in the reviewed profile catalog, not request fields. The engine drops every default
Linux capability and restores only namespaced `SYS_CHROOT`, which the non-root
Chromium sandbox requires; `SYS_ADMIN` remains absent.

## Durable data and state machine

Add migration `20260827_22_sandbox.py` and keep ORM metadata exactly synchronized so
`alembic check` remains clean.

### `sandbox_profiles`

Seed an immutable row for `static-website@1` containing its identity, version,
fixed harness contract version, runtime-image contract key and build-manifest
digest, resource ceilings, security options, allowed project kind, and creation
timestamp. Runtime image ID is deployment input recorded per execution because a
local Compose build does not provide a stable registry digest; the runner must
resolve the profile contract to an exact image ID and reject a mutable tag,
unresolved image, or mismatched build-manifest label.

Profile, runtime source/lockfile, or harness changes insert a new profile version.
Seed data, image labels, and the Python profile catalog must fail closed when they
disagree.

### `sandbox_executions`

Store at least:

- UUID, selected `business_id`, and idempotency key;
- exact website project ID/version, specification ID/version, source digest, and
  build digest;
- profile ID/version, harness contract version, runtime image ID, and request
  digest;
- governance action ID and authorizing policy version ID;
- status, worker recovery count, attempt timestamps, heartbeat, and cancellation
  timestamp;
- effective-limit evidence and its digest;
- termination reason, exit code, bounded route/process results, stdout/stderr
  excerpts and hashes;
- cleanup status, cleanup attempts, cleanup timestamps, final resource count, and
  cleanup receipt digest; and
- created, started, finished, and updated timestamps.

Use database constraints for valid versions, non-negative counts, unique
business/idempotency, and allowed states. Large or attacker-controlled raw streams
must not be stored.

The state machine is:

```text
requested -> waiting_approval -> queued -> authorizing -> running -> cleaning
                     |              |           |          |           |
                     +-> rejected   +-----------+----------+           +-> succeeded
                                                |                      +-> failed
                                                +-> cancelled          +-> cancelled
                                                                       +-> timed_out
                                                                       +-> resource_exhausted
                                                                       +-> infrastructure_failed
                                                                       +-> cleanup_failed
```

`rejected`, `succeeded`, `failed`, `cancelled`, `timed_out`,
`resource_exhausted`, `infrastructure_failed`, and `cleanup_failed` are terminal.
The service owns all transitions; API payloads never set status directly. If
user-code outcome is known but cleanup fails, the terminal status is
`cleanup_failed` and the original outcome is retained in structured evidence.
Cancellation before runner submission is terminal only after proving no receipt or
labeled resource exists. Once the runner has been contacted, every outcome passes
through `cleaning` before a terminal state.

## Runner boundary and protocol

Create a minimal `apps/sandbox-runner` service and a separate
`apps/sandbox-runtime` image. Do not add the Docker SDK or socket to the existing API
image.

Compose topology:

- `worker` joins the default application network and an internal
  `sandbox-control` network;
- `sandbox-runner` joins only `sandbox-control`, exposes no host port, receives no
  application/provider credentials, and owns a runner-state volume;
- the runner alone receives Docker Engine access in the portable local backend;
- generated children use `network=none`, no Compose network, and no published port;
  and
- API and web do not join `sandbox-control`.

Use a small authenticated, versioned protocol with operations equivalent to
`execute`, `inspect`, `cancel`, and `acknowledge`. Every message includes the
execution ID, profile/version, and request digest. Responses use a strict schema,
bounded sizes, explicit error codes, and no engine-native option passthrough.

The runner's operational receipt ledger records request identity, child resource
labels, current state, bounded result evidence, and cleanup proof. Atomic receipt
writes and unique engine labels provide idempotency across HTTP retries and runner
restarts. A startup/periodic janitor removes stale labeled resources and finalizes
their receipts. Application PostgreSQL remains authoritative for user-visible state.

Before start, the runner must inspect the created child and compare effective engine
settings to the selected profile. Any mismatch prevents execution and triggers
cleanup. After termination, cleanup must stop/remove the child and remove writable
state, then query by execution label and prove zero resources remain.

## Governance and application flow

Add `internal.code.execute` and `foundora.sandbox.website` to the code-reviewed
governance catalogs with minimum risk R2. Tool permission remains selected-business
scoped; global kill switch and active policy behavior remain unchanged.

The protected owner flow is:

1. Owner requests execution for the current active project.
2. The service locks and validates the business/project, recomputes the source/build
   digests, builds the canonical request digest, and creates the R2 governance action
   and `requested`/`waiting_approval` execution atomically.
3. Existing governance UI records the explicit owner decision.
4. Owner starts the approved execution. The service re-locks the project and
   governance records, rejects staleness or mismatched digests, transitions to
   `queued`, commits, and enqueues its deterministic RQ job ID.
5. The worker re-authorizes immediately before contacting the runner. Denial is
   durable and no child is created.
6. The worker persists returned evidence, enters `cleaning` if needed, verifies the
   terminal cleanup receipt, and commits the terminal state and outbox event in one
   transaction.

Queue failure must be persisted. Worker maintenance reconciles queued/stale
executions with bounded recovery attempts. Recovery asks the runner for the existing
receipt before it can submit an execute request. Exhausted or lost infrastructure
state becomes an honest terminal failure and still invokes janitor verification.

Add protected, selected-business endpoints and UI for:

- requesting execution of the current project;
- starting an approved execution and cancelling a nonterminal execution;
- listing bounded execution history; and
- inspecting the exact pinned inputs, governance evidence, limits, outcome,
  runtime evidence, and cleanup proof.

Use existing CSRF, origin, authentication, business-selection, error-envelope, rate
limit, `Cache-Control: no-store`, and safe-rendering conventions. Do not return raw
source archives or unbounded logs from dashboard endpoints.

## Events and observability

Register `sandbox.execution.finished` version 1. Publish it only after a terminal
execution row and verified cleanup evidence are committed. The bounded payload
includes business ID, execution ID, project ID/version, profile ID/version, outcome,
termination reason, duration, effective-limit digest, cleanup status, and correlation
metadata. It excludes source, logs, environment, and credentials.

Add structured runner/worker logs and metrics for launches, outcome classes,
timeouts, resource exhaustion, rejected requests, request-digest conflicts,
recovery, cleanup attempts/failures, janitor removals, duration, and remaining
labeled resources. Readiness must fail if the runner cannot resolve the pinned image
or exercise the engine API safely; it must not launch generated code as a health
check.

## Implementation slices

### Slice 0 — Contract, threat fixtures, and runtime image (**COMPLETE**)

- Add the profile/harness schemas and canonical hashing rules.
- Build the pinned non-root browser runtime and fixed entrypoint.
- Create malicious fixtures for CPU, memory, process, filesystem, network,
  environment, output, timeout, and malformed-result behavior.
- Prove the runtime can load a valid Phase 21 route with browser sandboxing enabled;
  do not use `--no-sandbox`.

Exit: profile request/result schemas reject all undeclared fields, the image resolves
to an immutable ID, and the fixed harness passes unit tests without app credentials.

### Slice 1 — Schema and domain service (**COMPLETE**)

- Add the migration, models, repositories, state transitions, digest validation,
  status serialization, and profile seed/catalog parity check.
- Add R2 action/tool catalog entries and business-scoped permission support.
- Add unit tests for constraints, stale project rejection, idempotency, governance
  target pinning, and illegal state transitions.

Exit: fresh upgrade, downgrade/re-upgrade, model metadata comparison, and
`alembic check` pass.

### Slice 2 — Trusted runner and cleanup reconciler (**COMPLETE**)

- Implement authenticated versioned runner operations and strict size limits.
- Apply and inspect every container control before start.
- Implement atomic receipts, deterministic labels, idempotent replay, cancellation,
  bounded evidence capture, `finally` cleanup, and startup/periodic janitors.
- Add Compose networks, runner-state volume, engine boundary, health check, and
  pinned runtime-image configuration.

Exit: direct runner integration tests prove that callers cannot override capabilities
and that every test child leaves zero labeled resources.

### Slice 3 — Worker orchestration and recovery (**COMPLETE**)

- Add deterministic RQ delivery, runtime authorization, runner client, heartbeat,
  cancellation, evidence persistence, and bounded recoveries.
- Reconcile stale rows against receipts before any retry and make terminal commit
  contingent on cleanup proof.
- Keep application credentials only in the worker; inspect child environment in
  tests to prove they are absent.

Exit: worker termination at pre-launch, running, result-return, and cleanup
checkpoints never duplicates execution and always converges to a truthful terminal
state.

### Slice 4 — Protected API and owner UI (**COMPLETE**)

- Add request/start/cancel/list/detail APIs and a selected-business sandbox page.
- Reuse the durable governance approval surface and make approval/start state clear.
- Show pinned project/profile, effective controls, runtime outcome, and cleanup
  status without rendering untrusted output as markup.
- Add server-action, cookie-adoption, CSRF, timeout, and no-store tests.

Exit: an owner can approve, run, inspect, and cancel through the UI; cross-business,
stale, unauthenticated, and unapproved attempts fail without launching a child.

### Slice 5 — Events, operations, and recovery drills (**COMPLETE**)

- Add the event contract/consumer fixtures and transactional outbox publication.
- Add structured metrics/logging, readiness, janitor operation, and operator notes.
- Extend deterministic smoke coverage to confirm runner health and zero residual
  resources without requiring a model provider.

Exit: terminal event delivery is idempotent, recovery drills converge, and normal
Compose shutdown/startup leaves no child resources.

### Slice 6 — Adversarial acceptance and phase closeout

Run the full verification matrix below, document evidence in
`docs/phase-22-sandbox.md`, update the implementation ledger only after every gate
passes, then stop before Phase 23.

## Verification matrix

| Requirement   | Required proof                                                                                                                                         |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| CPU           | Engine inspection matches one-CPU profile; CPU-bound fixture remains capped and host/other services stay healthy                                       |
| Memory        | Inspection matches 512 MiB/no-extra-swap; allocation fixture terminates as `resource_exhausted` without host impact                                    |
| Timeout       | Infinite-loop/sleep fixtures are terminated within the 60-second limit plus documented grace                                                           |
| Process count | Fork/process fixture cannot exceed 128 and is classified without destabilizing the runner                                                              |
| Capabilities  | Engine inspection shows drop `ALL`, add only `SYS_CHROOT`, `no-new-privileges`, and no `SYS_ADMIN`                                                     |
| Filesystem    | Root and source writes fail; traversal and host-path probes fail; writable tmpfs byte limits are enforced                                              |
| Network       | External IP, DNS, Compose service, and runner probes fail; internal loopback harness still works                                                       |
| Credentials   | Environment, filesystem, metadata, and Docker-socket probes find none of the seeded sentinel credentials                                               |
| Output        | Infinite stdout/stderr and oversized result fixtures are capped and safely persisted                                                                   |
| Image/command | Unknown image/profile and command/environment/mount override fields are rejected before create                                                         |
| Governance    | Missing/rejected approval, kill switch, disabled tool, stale policy/target, and wrong business launch no child                                         |
| Idempotency   | Concurrent/replayed execute requests create at most one child and return one matching receipt                                                          |
| Cleanup       | Success, nonzero exit, OOM, PID exhaustion, timeout, cancel, worker death, runner restart, and malformed result all converge to zero labeled resources |
| Truthfulness  | No outcome becomes `succeeded` without route success, valid bounded evidence, and verified cleanup                                                     |

## Quality and acceptance gates

Before Phase 22 can be marked complete:

- Python formatting, Ruff, mypy, all API tests, web formatting/lint/typecheck/tests,
  and production web build pass;
- a fresh database upgrades to head, downgrade/re-upgrade succeeds, ORM metadata
  matches the migration, and `alembic check` passes;
- Compose configuration validates, migration completes, and every long-running
  default service including the runner is healthy;
- deterministic smoke tests prove a successful sandbox execution without provider
  keys and prove zero labeled resources afterward;
- every verification-matrix attack passes repeatedly, including interruption and
  concurrent-idempotency cases;
- API, worker, PostgreSQL, Redis, web, and unrelated Foundora workflows remain
  healthy during resource attacks;
- no application/provider credential is present in runner configuration, child
  environment, child filesystem, logs, receipts, events, or API responses;
- `npm audit --audit-level=high` reports no high/critical web vulnerability and
  pinned runner/runtime base images are reviewed for high/critical findings;
- documentation records exact image IDs, profile values, commands, results, and
  known limitations; and
- Phase 23 remains untouched.

## Likely change surface

- `apps/api/alembic/versions/20260827_22_sandbox.py`
- `apps/api/src/foundora/models.py`
- `apps/api/src/foundora/governance/registry.py`
- `apps/api/src/foundora/sandbox/`
- `apps/api/src/foundora/api/sandbox.py`
- `apps/api/src/foundora/events/contracts.py`
- `apps/api/src/foundora/worker.py`
- `apps/api/tests/`
- `apps/sandbox-runner/`
- `apps/sandbox-runtime/`
- `apps/web/app/sandbox/` and related server actions/tests
- `compose.yaml`, `.env.example`, `scripts/quality.ps1`, `scripts/ci.ps1`, and
  `scripts/smoke.ps1`
- `docs/phase-22-sandbox.md` and `docs/implementation-status.md` at closeout

## Explicitly deferred

- Phase 23 QA scoring, screenshots, visual diffs, accessibility/SEO assertions,
  form testing, and performance judgments;
- a public or shareable preview URL;
- deployment, hosting, DNS, certificates, analytics, or production traffic;
- arbitrary repositories, commands, languages, frameworks, dependency installers,
  or user-selected images;
- outbound network allowlists or browser access to third-party assets; and
- claims of hard hostile-kernel or multi-tenant production isolation.
