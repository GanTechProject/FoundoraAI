$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

Invoke-Checked { docker compose up --build --detach --wait }

$apiPort = if ($env:API_PORT) { $env:API_PORT } else { "8000" }
$webPort = if ($env:WEB_PORT) { $env:WEB_PORT } else { "3000" }

$readiness = Invoke-RestMethod -Uri "http://localhost:$apiPort/health/ready"
if ($readiness.status -ne "ready") {
    throw "API readiness did not report ready"
}

$webResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:$webPort"
if ($webResponse.StatusCode -ne 200) {
    throw "Frontend did not return HTTP 200"
}

Invoke-Checked { docker compose exec -T postgres pg_isready -U foundora -d foundora }
Invoke-Checked { docker compose exec -T redis redis-cli ping }
Invoke-Checked { docker compose exec -T postgres psql -U foundora -d foundora -tAc "SELECT version_num FROM alembic_version WHERE version_num = '20260822_01'" }
Invoke-Checked { docker compose exec -T worker python -m foundora.worker_health }

Invoke-Checked { docker compose ps }
