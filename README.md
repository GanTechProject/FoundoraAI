# Foundora

Foundora is an owner-operated AI business launch and operating system. The current implementation includes the portable runtime, secure single-owner authentication, multi-business workspace, founder-approved onboarding, the provider-independent model gateway, the provenance-first business brain, the versioned agent and skill runtime, the durable task and workflow engines, the policy, risk, and approval engine, the internal event bus, provider-neutral knowledge retrieval, curated memory, executive planning, source-backed research agents, founder-approved evidence-linked business strategy, and immutable founder-approved product and offer portfolios.

No deployment provider has been selected. The application contains no AWS-, Azure-, Vercel-, Railway-, Render-, or other provider-specific runtime architecture.

## Required local runtime

Docker Desktop running Linux containers and Docker Compose are required. Do not substitute ad-hoc host services. The verified development toolchain is:

| Runtime           | Exact version |
| ----------------- | ------------: |
| Docker Engine     |        29.7.2 |
| Docker Compose    |         5.4.0 |
| Node.js           |   24.19.0 LTS |
| npm               |       11.17.0 |
| Python            |       3.13.15 |
| PostgreSQL        |          18.6 |
| Redis Open Source |         8.2.8 |

Application dependencies are exactly pinned in `package-lock.json`, `apps/web/package.json`, `apps/api/pyproject.toml`, and the Python production/development lock files under `apps/api/`. Container image tags are pinned in the Dockerfiles and `compose.yaml`.

| Core package      | Exact version |
| ----------------- | ------------: |
| Next.js           |        16.3.2 |
| React / React DOM |        19.2.8 |
| TypeScript        |         6.0.3 |
| FastAPI           |       0.141.1 |
| SQLAlchemy        |        2.0.52 |
| Alembic           |        1.19.1 |
| redis-py          |         8.1.0 |
| RQ                |        2.11.0 |
| pwdlib            |         0.3.0 |
| argon2-cffi       |        25.1.0 |
| HTTPX             |        0.28.1 |
| jsonschema        |        4.26.0 |
| pgvector (Python) |         0.5.0 |
| pgvector (server) |         0.8.6 |

Version selection was verified on 2026-08-22 against the official [Node.js release table](https://nodejs.org/en/about/previous-releases), [Python 3.13.15 release](https://www.python.org/downloads/release/python-31315/), [PostgreSQL version policy](https://www.postgresql.org/support/versioning/), [Redis 8.2 release notes](https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/redisce/redisos-8.2-release-notes/), and [Next.js release blog](https://nextjs.org/blog).

## One local startup procedure

From the repository root in PowerShell:

```powershell
docker compose up --build --detach --wait
docker compose ps
```

The migration container runs `alembic upgrade head` before the API or worker starts. Once all health checks pass:

- frontend: http://localhost:3000
- API readiness: http://localhost:8000/health/ready

Health endpoints remain public for orchestration. API documentation is disabled because an unauthenticated documentation surface is unnecessary for the owner-operated runtime.

## Provision the owner

There is no public signup and Foundora will not create a default credential. After the first startup, provision the single owner from an interactive terminal:

```powershell
docker compose exec api python -m foundora.owner --email you@example.com
```

The password prompt is hidden and requires confirmation. Passwords must contain 15–128 characters; all characters, including spaces and Unicode, are allowed. Use a password manager and a unique passphrase.

If the owner loses access, this explicit recovery command replaces the credential and revokes every existing session:

```powershell
docker compose exec api python -m foundora.owner --email you@example.com --replace-existing
```

Do not place an owner password in `.env`, Compose, shell history, source code, or frontend configuration. The non-interactive `--password-env` option exists only for controlled automation such as the smoke suite; the named environment variable is read transiently and never persisted by Foundora.

Open http://localhost:3000 after provisioning. Unauthenticated requests are redirected to the owner login page. Authenticated owners land at `/workspace`, where they can create and switch businesses, maintain each selected business's profile, lifecycle status, operating preferences, and goals, or archive it. Security controls remain available at `/settings/security`.

Business selection is stored per authenticated session. Creating a first business selects it automatically; creating additional businesses does not silently change the current context. Archived businesses remain visible as historical registry entries but cannot be selected. Phase 03 has no demo business seed and does not assume which real business the founder will launch.

For a selected business, open `/onboarding` from the workspace. The wizard records idea/existing-business status, name, industry, geography, problem, target audience, offer, goals, existing assets, constraints, budget context, brand preferences, and founder-declared services. Each step saves with optimistic revision protection and can be resumed later. Submission freezes a draft for review; a separate explicit approval creates or replaces the approved profile. Reopening an approved profile leaves the last approved version authoritative until a revision is approved again.

Open `/settings/ai` to inspect configured providers, validate their selected models, review routing and the governed price registry, run a tightly budgeted live check, and inspect business-scoped usage. Credentials are optional server environment variables: `OPENAI_API_KEY`, `GEMINI_API_KEY`, and `ANTHROPIC_API_KEY`. A missing credential disables its provider without mock output. Prompts and model output are not persisted; attempt metadata records tokens, estimated micro-USD cost, latency, retry/fallback lineage, and sanitized failures.

The default route is OpenAI `gpt-4o-mini`, followed by Gemini and Anthropic fallback for explicitly standard-sensitivity requests. Sensitive requests cannot cross providers. Defaults can be changed with the `FOUNDORA_MODEL_*` variables listed in `.env.example`, but model identifiers remain constrained to the code-reviewed registry. Current registry pricing and its review date are documented in `docs/phase-05-model-gateway.md`.

Open `/brain` for the selected business's unified context. The builder exposes an
explicit purpose, token ceiling, and source selection, then shows every source's
authority, version, validity, inclusion decision, and integrity fingerprint.
Completed and cancelled goals cannot enter compiled context, onboarding drafts are
never treated as approved facts, and future strategy, customer, KPI, and decision
sources are shown as unavailable until their phases implement them.
Knowledge enters context only through an explicit retrieval query and retains its
source/document/chunk citation rather than becoming an approved fact.
Active durable memory enters as a separate source with its type, epistemic status,
acceptance route, confidence, revision, and provenance. Working memory never
enters general business context without an explicit execution scope.

Open `/agents` to inspect the versioned agent and skill registries and execute the seeded
read-only runtime verification agent. A run snapshots its selected-business input,
pins the exact agent version, executes asynchronously through the RQ worker and
model gateway, and persists status, messages, structured output or sanitized
failure, cancellation timestamps, and linked usage attempts. The built-in agent is
R0 and manual-run-only, with no tools or external side effects. Its version 2 may
invoke only the assigned `summarize-business-context@1` contract. The registry also
exposes harmless structured-plan and provided-data analysis skills, but compatibility
does not authorize them.

Open `/tasks` to create selected-business draft tasks, optionally link them to an
existing goal, set priority and due date, and assign the founder or a current
version-pinned agent. The task inspector exposes valid lifecycle transitions,
dependency blockers, retry budget, and append-only events. A task cannot be queued
or run until all dependencies are complete; dependency cycles and cross-business
references are rejected. Failed-task retry is bounded and idempotent. This phase
records queued work but does not itself execute a workflow or grant an approval.

Open `/workflows` to inspect immutable workflow graphs and their selected-business
run ledger. A run pins an exact definition version, persists all step state before
queue delivery, enforces dependency and conditional-branch ordering, and resumes
through idempotent owner, wait, or child-agent checkpoints. Every internal tool,
compensation, and owner checkpoint now crosses the Phase 11 governance boundary
before execution. External provider tools remain unavailable.

Open `/governance` to inspect the immutable active policy, code-derived R0–R5
risk catalog, selected-business autonomy and spend ceilings, internal tool
permissions, durable action/approval ledger, and append-only audit evidence. R3
and R4 always require explicit owner approval, R5 is denied, spend defaults to
zero, and authorization rechecks live controls. The global kill switch is
enforced beneath workflow prompts. Authorization never claims an external side
effect occurred.

Open `/events` to inspect the selected business's versioned domain-event contracts,
immutable event envelopes, and per-consumer delivery state. Business, goal, task,
and approval mutations publish their implemented events in the same PostgreSQL
transaction as domain state. The worker completes registered handlers atomically,
retries failures with bounded backoff, and moves exhausted deliveries to a durable
dead-letter state that the owner can explicitly redrive. Redis is not the durable
event authority.

Open `/knowledge` to register selected-business source provenance, upload bounded
UTF-8 text, Markdown, JSON, or CSV files, search indexed chunks, inspect exact
citations, and invalidate a document or source. Original files use a local Docker
volume behind a storage interface. Versioned local embeddings are searched in
PostgreSQL through pgvector. Knowledge remains evidence until the Phase 14 curator
and acceptance boundary explicitly promote it.

Open `/memory` to configure the selected business's acceptance policy, submit
curator proposals, explicitly accept or reject facts and other durable claims,
inspect immutable revisions and source provenance, filter the ledger, and
invalidate stale memory. Founder review is the default. Semantic facts,
decisions, and preferences cannot auto-approve; exact duplicates merge instead
of creating conflicting records. Credential-shaped content is rejected, and
working memory requires an execution scope and expiry within seven days. Phase 14
makes no model-provider call.

The `/agents` registry now includes the `founder-ceo@1` and
`chief-of-staff-planning@1` executive contracts. An explicit manual run snapshots
the selected business, then returns a proposed plan with its exact context ID,
integrity hash, source references, assumptions, limitations, risk, approval
needs, priorities or dependency graph, and candidate specialist work. Both
agents are R0 advisory-only, have no tools or assigned skills, and cannot create
tasks or workflows, grant approval, spend, contact people, or claim delegation
occurred. Explicit runs use the provider-independent model gateway; unavailable
providers fail honestly.

The registry also includes `market-research@1`,
`competitor-intelligence@1`, and `customer-research@1`. Each explicit run first
uses the provider-neutral `SearchProvider` boundary to retrieve selected-business
evidence, then pins its exact source, retrieval date, excerpt, and integrity hash
before model execution. The default `RegisteredKnowledgeSearchProvider` searches
only active, founder-registered Phase 13 knowledge; no public-web search vendor is
configured or implied. Supported findings must reproduce exact pinned citations.
Unsupported claims remain visibly flagged with confidence and limitations, and a
competitor name cannot be returned as supported unless it occurs in cited
evidence. All three agents are manual R0 advisors with no model-invoked tools or
side effects.

The registry also includes `business-strategist@1`. A strategist run requires
one completed, validated, supported run from each Phase 16 research specialist
and founder-approved facts in its selected-business context. It proposes all
nine Phase 17 artifacts, and every item must reproduce exact approved-fact and
supported-finding references. Pricing remains a hypothesis and assumptions state
how they require validation. Open `/strategy` to review completed proposals and
explicitly approve one with optimistic version protection. Approval creates the
versioned `approved_strategy` Business Brain source and a transactional audit
event; the agent cannot self-approve or execute the strategy.

The registry also includes `product-offer@1`. It requires the exact current
founder-approved strategy, pins every strategy item reference, and proposes target
segments, products/services, benefits, packages, and explicit prices. All entities
remain proposed and all prices remain marked `requires_validation` until reviewed.
Open `/products-offers` to approve a proposal. Each approval creates a new immutable
portfolio version, supersedes the previous active version, publishes a transactional
event, and exposes the active portfolio as authoritative `products_services` Business
Brain data. The agent has no tools, provider selection, launch, sales, delivery, brand,
or self-approval authority.

The registry also includes `brand-strategist@1`. It requires the exact current
founder-approved strategy and the active founder-approved product/offer portfolio
derived from that strategy. Each proposed brand strategy, positioning statement,
naming analysis, voice rule, message, tagline, visual direction, brand rule, and
asset reference cites both immutable sources. Naming availability is explicitly
unchecked and asset references remain proposals. Open `/brand` to approve a completed
proposal. Approval creates an immutable brand-system version, supersedes the prior
active version, publishes `brand.approved`, and exposes both the complete system and
its approved `brand_rules` through the provider-neutral Business Brain. The agent
cannot self-approve, create assets, publish, or claim trademark/domain availability.
The schema head is `20260825_19`.

Local sessions use `HttpOnly`, `SameSite=Strict` cookies. A session expires after 30 minutes without activity and absolutely after eight hours. Production configuration is rejected unless the public origin uses HTTPS and secure cookies are enabled.

PostgreSQL and Redis bind only to localhost. PostgreSQL uses trust authentication only inside this local Compose network; production must supply independently managed authentication when a deployment phase selects an environment.

Stop services without removing data:

```powershell
docker compose down
```

## Verification

Run every formatting, lint, type-check, test, build, migration, dependency-reachability, process-health, and HTTP smoke check with:

```powershell
./scripts/verify.ps1
```

The verification script leaves the primary application running for inspection. Authentication, business-isolation, onboarding approval-boundary, capped real-provider gateway, agent lifecycle, assigned-skill boundary, task persistence/dependency/retry, workflow checkpoint/resume, governance bypass/kill-switch, event delivery/dead-letter, knowledge ingestion/retrieval, memory policy/provenance, executive-contract, source-backed research, strategy approval-boundary, product/offer approval-boundary, and brand approval-boundary smoke checks use temporary isolated databases and containers that are removed automatically, so existing development owner and business data are not modified. The smoke suite can incur a small provider charge within the enforced operation budgets documented in the Phase 05, Phase 07, and Phase 08 evidence. Phases 09 through 14 make no provider call; Phases 15 through 19 call a model only when the founder explicitly queues an agent run. The Phase 16 SearchProvider and Phase 17 through 19 contract/approval smokes are local and deterministic. Individual suites are available through `./scripts/quality.ps1` and `./scripts/smoke.ps1`.

Push and pull-request CI uses `./scripts/ci.ps1`, which runs deterministic quality,
build, migration, health, and process gates without requiring or billing external
model providers. Live-provider acceptance is an explicit manual GitHub Actions
job and receives provider credentials only from repository secrets.

## Repository shape

```text
apps/web/       Next.js web process
apps/api/       FastAPI app, Alembic migrations, and RQ worker process
docs/           Specifications, architecture decisions, and phase evidence
scripts/        Reproducible PowerShell quality and smoke checks
compose.yaml    Portable local service topology
```

Redis carries queues, login rate-limit counters, and ephemeral coordination; PostgreSQL remains the durable source of truth. The worker consumes the `foundora` RQ queue and reconciles durable event deliveries directly from PostgreSQL. Business workspaces, onboarding drafts, founder-approved profiles and strategies, immutable product/offer versions, agent, skill, and workflow definitions and versions, exact assignments, agent runs and messages, tasks, dependencies, task events, workflow runs, step runs, workflow events, policy versions, governance controls, action approvals, audit evidence, domain events, consumer deliveries, knowledge sources/documents/chunks/vectors, memory policies/proposals/records/revisions/provenance, and model usage are durable PostgreSQL records. Original knowledge files use the configured storage abstraction. Business-brain context remains derived from authoritative selected-business records, explicitly retrieved cited knowledge, and active curated memory. External provider tools and later operational domains remain deferred to their authorized phases.
