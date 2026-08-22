# Foundora

Foundora is an owner-operated AI business launch and operating system. The current implementation is the Phase 01 foundation: a cloud-portable Next.js web application, FastAPI service, PostgreSQL database, Redis-backed worker, migrations, structured logs, health checks, and Docker Compose development environment.

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
- API documentation: http://localhost:8000/docs

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

The verification script leaves the application running for inspection. Individual suites are available through `./scripts/quality.ps1` and `./scripts/smoke.ps1`.

## Repository shape

```text
apps/web/       Next.js web process
apps/api/       FastAPI app, Alembic migrations, and RQ worker process
docs/           Specifications, architecture decisions, and phase evidence
scripts/        Reproducible PowerShell quality and smoke checks
compose.yaml    Portable local service topology
```

Redis carries queues and ephemeral coordination; PostgreSQL remains the durable source of truth. The worker consumes the `foundora` RQ queue. Domain tables and product behavior are deliberately deferred to their authorized phases.
