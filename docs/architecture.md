# Foundora Architecture Baseline

## Current architecture

The implementation through Phase 07 is a portable modular monorepo:

- `apps/web`: a standalone-output Next.js process with owner authentication, security settings, and the server-rendered business workspace;
- `apps/api`: a FastAPI process with PostgreSQL and Redis readiness probes, correlation IDs, and structured JSON logging;
- `apps/api`: a separately runnable RQ worker consuming the Redis-backed `foundora` queue;
- Alembic: a gated migration process that must complete before API and worker startup;
- a provider-independent model gateway with native HTTP adapters, governed routing,
  budgets, streaming, structured output, and business-scoped usage evidence;
- a selected-business Context Service with explicit source selection, conservative
  token ceilings, provenance, and stale/invalidated source exclusion;
- a versioned agent registry and durable run runtime that snapshots structured
  selected-business input, delegates model execution to the gateway, and records
  lifecycle, messages, failures, cancellation, and usage linkage;
- `compose.yaml`: health-gated PostgreSQL, Redis, migration, API, worker, and web services;
- `scripts/`: containerized quality and smoke gates used locally and by CI.

No deployment environment or provider-specific application architecture is selected.

## Target shape

Foundora V1 will be an owner-operated, modular monolith with separately deployable web, API, worker, and scheduler processes. It is not a public multi-tenant SaaS.

```text
Founder
  -> Next.js web application
  -> FastAPI application
       -> business/context services
       -> goals, tasks, workflows, agents, skills
       -> policy, risk, approval, and budgets
       -> tool runtime and provider adapters
       -> events, scheduling, observability
       -> PostgreSQL / Redis / object storage abstraction
  -> durable worker process
  -> scheduler process (emits work; contains no business logic)
```

## Strategic architecture decisions

1. **Modular monolith first.** Domain boundaries are explicit in code and data, but V1 avoids premature microservices and Kubernetes.
2. **Process separation without service sprawl.** Web, API, worker, and scheduler have distinct entry points and health behavior while sharing versioned domain packages.
3. **Single owner, multiple businesses.** Authentication is owner-focused, while every operational record is scoped to a business from the first relevant domain phase. A future tenant boundary must not be confused with `business_id`.
4. **Server-side secrets and provider adapters.** External services are reachable only through adapters and governed tools. Missing credentials disable capability; they never activate mock success paths.
5. **PostgreSQL as durable truth.** Redis is for queues, locks, caching, and ephemeral coordination—not the sole source of durable business state. Object storage is abstracted.
6. **Governed execution.** Agent -> skill -> workflow/tool -> policy -> provider is the mandatory action path. R3/R4 actions require approval by default, and a global kill switch must be enforceable beneath agent prompts.
7. **Transactional state transitions.** Important work uses explicit states, idempotency keys, append-only events/audit evidence, and safe retries. Durable side effects must not rely on model narration.
8. **Evidence and provenance by construction.** Research, knowledge, memory, metrics, external actions, and provider results retain source and timestamp metadata. Assumptions remain distinct from approved facts.
9. **Real-state UI.** Empty future sections stay hidden behind implementation-backed feature flags. The UI never fabricates connected, published, deployed, paid, running, or completed states.
10. **Incremental schema.** Database tables and provider interfaces are introduced only in their authorized phase; Phase 01 must not create the entire future domain model.

## Implemented foundation through Phase 07

The verified baseline is:

- npm workspaces for repository orchestration, avoiding an unnecessary package-manager prerequisite;
- Next.js + React + TypeScript for the web application;
- Python + FastAPI + Pydantic + SQLAlchemy + Alembic for API and domain persistence;
- PostgreSQL and Redis via Docker Compose;
- a dedicated Python worker using RQ 2.11.0 as the Redis-backed durable queue adapter;
- structured JSON logging and correlation IDs from the first executable phase;
- contract/schema generation or a shared versioned contract boundary rather than duplicated handwritten DTOs;
- CI gates for formatting, lint, type checking, unit tests, migration validation, and production builds.
- a single server-provisioned owner identity with Argon2id credentials;
- PostgreSQL-backed opaque sessions with CSRF tokens, expiration, rotation, and revocation;
- Redis-backed login throttling, exact-origin enforcement, and hardened HTTP response headers;
- a server-rendered login boundary and protected owner security settings.
- a business workspace service that resolves operational state exclusively through the authenticated session's selected business;
- durable business profiles, lifecycle status and archive state, validated timezone/currency/locale preferences, and goals;
- per-session business selection, with owner checks on every operational query and selection cleared across sessions when a business is archived;
- a protected server-rendered workspace for creating, switching, and maintaining multiple businesses.
- a four-step, server-rendered onboarding wizard with durable progress and optimistic revision checks;
- separate mutable onboarding drafts and versioned founder-approved profiles, with a frozen review transition between them;
- an explicit fact-promotion boundary: drafts and future suggestions are never read as approved facts, and only founder approval updates the approved profile;
- founder-declared service context that does not imply provider authentication or connectivity.
- server-only OpenAI, Gemini, and optional Anthropic adapters behind a Foundora-owned
  provider contract and code-reviewed model registry;
- bounded retry and standard-only fallback routing, provider configuration
  validation, structured responses, and server-sent-event streaming;
- shared operation token/cost ceilings and durable business-scoped attempt metadata
  without storing prompts, output, keys, or raw provider error bodies;
- a protected AI settings dashboard backed entirely by live configuration and
  persisted usage state.
- an on-demand business context assembler that reads only live workspace state,
  founder-approved onboarding facts, and business goals for the selected business;
- canonical model-ready JSON with fixed source priority, one-token-per-UTF-8-byte
  budgeting, source-level validity and selection decisions, and SHA-256 integrity
  fingerprints;
- explicit unavailable-source reporting for later strategy, knowledge, task,
  customer, KPI, decision, and memory domains, with no fabricated replacements.
- immutable agent-version contracts covering purpose, responsibilities,
  permissions, model policy, data scope, schemas, evaluation, and escalation;
- a manual-only R0 verification agent with no tools, skills, credentials, or
  external side effects;
- durable `queued`, `running`, `waiting_tool`, `waiting_approval`, `completed`,
  `failed`, and `cancelled` states, with worker claims and terminal transitions
  serialized in PostgreSQL;
- structured input/output validation, selected-business run inspection,
  cancellation, sanitized persisted errors, and model-attempt usage linked to the
  run and shared operation identity.

Exact runtime, framework, library, and container versions are recorded in the root `README.md`, lock files, manifests, Dockerfiles, and Compose file. Phase evidence is recorded in the corresponding `docs/phase-*.md` files.

## Dependency direction

```text
UI -> API contracts
API -> application services -> domain modules
application services -> policy / repositories / events
agents -> skills -> workflows/tools -> policy -> provider adapters
workers -> the same application services (never duplicate business rules)
scheduler -> enqueue/event boundary only
infrastructure adapters -> PostgreSQL / Redis / storage / external providers
```

Dependencies should point inward toward domain contracts. Provider SDK types, ORM models, and web-framework request objects must not become business-domain APIs.

## Reliability and security invariants

- Autonomy defaults to `OFF` or `RECOMMEND`.
- Every external side effect has an idempotency strategy and a persisted provider reference where available.
- Approval state is checked at execution time, not only when a plan is created.
- Secrets never enter frontend bundles, logs, prompts, durable memory, or committed configuration.
- Failures persist honestly and remain observable; no catch path returns fabricated success.
- Every run pins an immutable agent version; later registry edits cannot rewrite
  historical execution contracts.
- One action must ultimately be traceable from UI request through task, agent, skill, tool/provider, and result.
- Tests must include timeouts, retries, duplicates, partial workflow failure, worker interruption, and approval bypass attempts as the relevant phases arrive.

## Evolution boundary

Future SaaS conversion may add organizations, tenants, plans, quotas, team RBAC, and tenant-owned secrets around reusable core modules. Those concerns are not implemented in V1 and must not distort owner-operated product delivery.
