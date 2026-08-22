# Foundora

Foundora is an owner-operated AI business launch and operating system. The current implementation includes the portable runtime, secure single-owner authentication, and the Phase 03 multi-business workspace. The founder can create, switch, profile, status, archive, configure, and set goals for independent businesses without introducing SaaS tenancy.

No deployment provider has been selected. The application contains no AWS-, Azure-, Vercel-, Railway-, Render-, or other provider-specific runtime architecture.

## Required local runtime

Docker Desktop running Linux containers and Docker Compose are required. Do not substitute ad-hoc host services. The verified development toolchain is:

| Runtime | Exact version |
|---|---:|
| Docker Engine | 29.7.2 |
| Docker Compose | 5.4.0 |
| Node.js | 24.19.0 LTS |
| npm | 11.17.0 |
| Python | 3.13.15 |
| PostgreSQL | 18.6 |
| Redis Open Source | 8.2.8 |

Application dependencies are exactly pinned in `package-lock.json`, `apps/web/package.json`, `apps/api/pyproject.toml`, and the Python production/development lock files under `apps/api/`. Container image tags are pinned in the Dockerfiles and `compose.yaml`.

| Core package | Exact version |
|---|---:|
| Next.js | 16.3.2 |
| React / React DOM | 19.2.8 |
| TypeScript | 6.0.3 |
| FastAPI | 0.141.1 |
| SQLAlchemy | 2.0.52 |
| Alembic | 1.19.1 |
| redis-py | 8.1.0 |
| RQ | 2.11.0 |
| pwdlib | 0.3.0 |
| argon2-cffi | 25.1.0 |

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

The verification script leaves the primary application running for inspection. Authentication and business-isolation smoke checks use temporary isolated databases and containers that are removed automatically, so an existing development owner or its businesses are not modified. Individual suites are available through `./scripts/quality.ps1` and `./scripts/smoke.ps1`.

## Repository shape

```text
apps/web/       Next.js web process
apps/api/       FastAPI app, Alembic migrations, and RQ worker process
docs/           Specifications, architecture decisions, and phase evidence
scripts/        Reproducible PowerShell quality and smoke checks
compose.yaml    Portable local service topology
```

Redis carries queues, login rate-limit counters, and ephemeral coordination; PostgreSQL remains the durable source of truth. The worker consumes the `foundora` RQ queue. Business profiles, preferences, goals, and per-session selection are durable PostgreSQL records. Business onboarding and later operational domains remain deferred to their authorized phases.
