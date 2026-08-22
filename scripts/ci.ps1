$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

& "$PSScriptRoot/quality.ps1"

Invoke-Checked { docker compose up --build --detach --wait }

$readiness = Invoke-RestMethod -Uri "http://localhost:8000/health/ready" -TimeoutSec 5
if ($readiness.status -ne "ready" -or
        $readiness.checks.postgresql.status -ne "up" -or
        $readiness.checks.redis.status -ne "up") {
    throw "API readiness did not confirm PostgreSQL and Redis"
}

$web = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:3000/login" -TimeoutSec 5
if ($web.StatusCode -ne 200) {
    throw "Frontend login route did not start successfully"
}

$migrationVersion = docker compose exec -T postgres psql -U foundora -d foundora -tAc `
    "SELECT version_num FROM alembic_version"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($migrationVersion)) {
    throw "Database migrations are not applied"
}

Invoke-Checked { docker compose exec -T worker python -m foundora.worker_health }
Invoke-Checked { docker compose ps }

Write-Output "Deterministic CI runtime gates passed at migration $($migrationVersion.Trim())"
