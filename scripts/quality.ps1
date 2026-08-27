$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

Invoke-Checked { docker compose config --quiet }

Invoke-Checked { docker compose --profile quality run --build --rm api-quality ruff format --check src tests alembic }
Invoke-Checked { docker compose --profile quality run --rm api-quality ruff check src tests alembic }
Invoke-Checked { docker compose --profile quality run --rm api-quality mypy src }
Invoke-Checked { docker compose --profile quality run --rm api-quality pytest }
Invoke-Checked { docker compose run --rm migrate }
Invoke-Checked { docker compose run --rm migrate alembic check }

Invoke-Checked { docker compose --profile quality run --build --rm web-quality npm run format:check }
Invoke-Checked { docker compose --profile quality run --rm web-quality npm run lint }
Invoke-Checked { docker compose --profile quality run --rm web-quality npm run typecheck }
Invoke-Checked { docker compose --profile quality run --rm web-quality npm run test }
Invoke-Checked { docker compose --profile quality run --rm web-quality npm run build }

Invoke-Checked { & "$PSScriptRoot/test-sandbox-runtime.ps1" }
Invoke-Checked { & "$PSScriptRoot/test-sandbox-runner.ps1" }
