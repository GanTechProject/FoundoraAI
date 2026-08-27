# Sandbox operations

This runbook covers the Phase 22 local Compose sandbox boundary. It does not
authorize arbitrary container execution, manual receipt edits, deployment, or Phase
23 QA.

## Healthy state

The runner is healthy only when its internal readiness endpoint can reach the Docker
Engine and resolve the reviewed runtime tag to an immutable `sha256:` image ID. The
health response also returns process-lifetime counters for launches, replays,
request-digest conflicts, cancellation, outcome classes, cleanup, janitor work,
duration, readiness, and remaining labeled resources. It contains no runner token,
source, output, environment, or application credential.

Use the same check as Compose:

```powershell
docker compose exec -T sandbox-runner node src/healthcheck.mjs
```

Inspect bounded runner and worker logs:

```powershell
docker compose logs --since 15m sandbox-runner worker
```

Terminal worker logs use `sandbox.execution.finished`; recovery summaries use
`sandbox.execution.recovered`. Runner logs use `sandbox_execute`,
`sandbox_janitor_completed`, and `sandbox_janitor_failed`. Treat
`cleanup_failed`, a nonzero `remaining_resources`, repeated infrastructure failure,
or request-digest conflict as an incident.

## Zero-resource check

Both commands must return no identifiers after a terminal execution or recovery
drill:

```powershell
docker ps --all --quiet --filter "label=foundora.sandbox.managed=true"
docker volume ls --quiet --filter "label=foundora.sandbox.managed=true"
```

Do not delete the PostgreSQL execution row or runner receipt to make an incident
appear resolved. They are reconciliation evidence.

## Recovery procedure

1. Engage the global governance kill switch if cleanup is failing or unexplained
   resources remain. This prevents a fresh execution-time authorization.
2. Preserve the execution ID, current API evidence, and bounded worker/runner logs.
3. Restart only the runner with `docker compose restart sandbox-runner`. Its startup
   janitor removes orphaned labeled containers and volumes, then finalizes interrupted
   receipts only after proving zero resources.
4. Wait for the runner to become healthy and repeat the zero-resource check.
5. Let worker maintenance reconcile the PostgreSQL row from the receipt. Recovery is
   bounded to three generations and uses a deterministic job identity.
6. Release the kill switch only after the runner is healthy, the labeled-resource
   queries are empty, and the execution has an honest terminal status with cleanup
   evidence.

If the runner stays unhealthy or labeled resources remain, keep execution disabled
and escalate for engine-level investigation. Do not manually fabricate success,
cleanup evidence, events, or receipts.

## Deterministic drills

`scripts/test-sandbox-runner.ps1` exercises success, failure, cancellation,
idempotent replay, concurrent launch, denial paths, zero-resource cleanup, and
startup-janitor reconciliation. `scripts/smoke.ps1` checks runner readiness and zero
managed resources before and after its application scenario without requiring a
model provider for the sandbox checks.
