# ADR-0026: Capability-constrained isolated generated-code execution

Status: Accepted

Date: 2026-08-27

## Context

Phase 21 creates immutable, dependency-free static website projects and proves a
controlled materialized build without executing generated JavaScript. Phase 22 must
execute that generated code while enforcing and verifying CPU, memory, wall-time,
process, filesystem, network, credential, and cleanup boundaries.

Generated code is untrusted even when it passed Phase 21 checks. It may loop,
allocate memory, fork processes, write files, probe the network, inspect its
environment, or attempt to escape its execution boundary. The existing API and
worker hold database, Redis, session, and model-provider authority, so running code
inside either process or giving either process direct Docker access would collapse
the intended trust boundary. A generic command or container API would also turn a
narrow website capability into an infrastructure-control capability.

Phase 22 is not deployment and must not create a public preview. Phase 23 owns
website QA judgment; Phase 24 owns deployment. The initial sandbox therefore needs
to execute only the exact static project shape already approved in Phase 21.

## Decision

### Trust boundary

Add a dedicated, internal-only `sandbox-runner` service as the sole component that
can control disposable execution containers. The API has no route to the runner and
the API and worker do not receive the Docker socket or equivalent engine authority.
Only the worker can reach the runner over a private Compose control network using a
dedicated service credential.

For the portable local runtime, the runner is a small trusted computing-base
component with narrowly scoped Docker Engine access. This authority is never
mounted or forwarded into a child container. Production may replace the backend
with a stronger isolation implementation without changing the application contract,
but it may not weaken the profile or expose a general container API.

The runner accepts only:

- a UUID execution identifier;
- a code-reviewed sandbox profile identifier and version;
- the exact immutable `WebsiteProjectVersion` identity and recorded source/build
  digests; and
- a bounded source archive reconstructed and revalidated by the worker.

Callers cannot supply an image, command, entrypoint, environment, mount, device,
network mode, capability, resource limit, or engine option. The runner rejects an
unknown profile, a request-digest mismatch, or a second request for the same
execution identifier with different content.

### Initial execution profile

Seed one immutable `static-website@1` profile. It accepts only a current Phase 21
project with an empty dependency manifest and the supported HTML, CSS, JavaScript,
JSON, and text file set. It uses a code-reviewed runtime image resolved to an
immutable image ID and a fixed trusted harness. Package installation, lifecycle
scripts, arbitrary commands, user-selected images, and network access are absent.

The harness starts a loopback-only static server inside the child and uses a
headless browser in that same child to load every approved route. This executes the
generated browser JavaScript and records process/runtime facts. It does not make
Phase 23 QA claims about visual quality, responsive behavior, accessibility, SEO,
forms, or performance.

The versioned profile initially applies these ceilings:

- one CPU;
- 512 MiB memory with no additional swap;
- 128 processes;
- 60 seconds wall time, followed by a bounded termination grace period;
- a read-only root filesystem and read-only generated source;
- bounded in-memory writable locations only, including `/tmp` and `/dev/shm`;
- no external or Compose network and no published ports;
- non-root UID/GID, the default Linux capability set dropped, only the namespaced
  `SYS_CHROOT` capability restored for Chromium's internal sandbox, no new
  privileges, no devices, no host namespaces, and a code-reviewed seccomp profile;
- a minimal fixed environment that is constructed from an allowlist rather than
  inherited from the runner; and
- bounded stdout, stderr, result, and writable-storage bytes.

Changing any ceiling or security option requires a new profile version and fresh
acceptance evidence. The runner records the effective engine configuration before
start so stored evidence describes enforced settings, not requested settings.
The `SYS_CHROOT` exception is fixed rather than caller-selectable: the Slice 0 probe
proved Chromium fails closed without it and succeeds with only that capability,
while `SYS_ADMIN` and every other dropped capability remain absent.

### Credentials and data

The runner receives no PostgreSQL, Redis, owner-session, model-provider, deployment,
or production credentials. The fixed child environment contains no secrets, Docker
socket, control token, application network access, host path, or sibling-container
metadata. Source is copied into a stopped child, rehashed, and made read-only before
the fixed entrypoint starts; host bind mounts are not used for generated source.

Logs and results are untrusted data. They are size-limited, normalized, safely
rendered, and stored as bounded evidence with hashes. They never become commands,
HTML, environment values, or policy input.

### Durable lifecycle and cleanup

Create a durable, selected-business `SandboxExecution` record with immutable input
pins for the project, source/build digests, profile/version, runtime image ID,
governance action, and request digest. Its controlled lifecycle adds applied limits,
result evidence, termination reason, timestamps, and cleanup evidence while
distinguishing queued, approval, running, cleaning, success, timeout, resource
exhaustion, infrastructure failure, and cleanup failure.

Redis/RQ provides delivery only; PostgreSQL remains the application source of truth.
The runner labels every child resource with the execution identifier and keeps a
small operational receipt ledger on a runner-only volume. Receipts make retries
idempotent and retain bounded terminal/cleanup evidence long enough for worker
reconciliation. They do not become business-state authority.

Cleanup runs in the runner's `finally` path after every success, failure, timeout,
client disconnect, and cancellation. Startup and periodic janitors reconcile
orphaned labeled resources. An execution cannot become `succeeded` until the runner
confirms the child is stopped and removed, writable state is removed, and no labeled
resources remain. Missing or unverified cleanup is `cleanup_failed`, never success.

### Governance and observability

Add code-reviewed action `internal.code.execute` and tool
`foundora.sandbox.website`, both classified R2. Initially every sandbox execution
requires an explicit owner approval under the existing durable policy engine,
regardless of the business autonomy setting. Authorization rechecks the active
policy, global kill switch, selected-business tool permission, exact target, and
data boundary immediately before launch. Approval cannot authorize a different
project, digest, profile, or request.

Publish one versioned `sandbox.execution.finished` event through the transactional
outbox only after durable terminal and cleanup evidence is stored. Structured logs
and metrics distinguish user-code outcomes from runner/infrastructure and cleanup
failures without including source or credential values.

## Consequences

- Generated code is separated from application credentials, databases, queues,
  host filesystems, networks, and container-control authority.
- Phase 22 has a small, testable execution surface instead of a general-purpose CI
  or container platform.
- The runner is security-critical infrastructure and requires stricter review,
  image pinning, negative tests, and operational monitoring than an ordinary
  application service.
- R2 approval adds founder friction, but prevents silent generated-code execution.
  Any later reduction in risk requires a new decision and evidence.
- Local Docker isolation reduces risk but is not presented as a hard multi-tenant or
  hostile-kernel boundary. A production deployment can adopt a remote sandbox,
  microVM, or stronger runtime behind the same contract.
- General dependencies, arbitrary builds, public previews, QA scoring, deployment,
  and domain/DNS work remain outside Phase 22.

## Supersession

This decision extends ADR-0004, ADR-0005, ADR-0006, ADR-0014, ADR-0016, ADR-0017,
and ADR-0025. It does not supersede them.
