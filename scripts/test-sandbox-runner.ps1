$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$runnerRoot = Join-Path $workspace "apps/sandbox-runner"

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Failure)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw $Failure
    }
}

$token = if ($env:FOUNDORA_SANDBOX_RUNNER_TOKEN) {
    $env:FOUNDORA_SANDBOX_RUNNER_TOKEN
} else {
    "foundora-local-sandbox-runner-token-v1"
}

Invoke-Checked { docker compose config --quiet } "Compose configuration is invalid"
Invoke-Checked { docker compose up --build --detach --wait sandbox-runtime sandbox-runner } `
    "Sandbox runner did not become healthy"
Invoke-Checked { docker compose exec -T sandbox-runner node --test test/contracts.test.mjs } `
    "Sandbox runner contract tests failed"
foreach ($pass in 1..2) {
    Invoke-Checked { docker compose exec -T sandbox-runner node test/integration.mjs } `
        "Sandbox runner integration probes failed on pass $pass"
}
Invoke-Checked { npm audit --prefix $runnerRoot --audit-level=high --package-lock-only } `
    "Sandbox runner dependency audit failed"

$runnerId = docker compose ps --quiet sandbox-runner
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($runnerId)) {
    throw "Sandbox runner container is unavailable"
}
$runner = docker inspect $runnerId | ConvertFrom-Json
$runnerNetworks = @($runner[0].NetworkSettings.Networks.PSObject.Properties.Name)
if ($runnerNetworks.Count -ne 1 -or $runnerNetworks[0] -ne "foundora_sandbox-control") {
    throw "Sandbox runner is not isolated to the private control network"
}
$forbiddenRunnerEnvironment = @($runner[0].Config.Env | Where-Object {
        $_ -match '^(OPENAI_API_KEY|GEMINI_API_KEY|ANTHROPIC_API_KEY|FOUNDORA_DATABASE_URL|FOUNDORA_REDIS_URL)='
    })
if ($forbiddenRunnerEnvironment.Count -ne 0) {
    throw "Sandbox runner received an application or provider credential"
}
$socketMount = @($runner[0].Mounts | Where-Object { $_.Destination -eq "/var/run/docker.sock" })
if ($socketMount.Count -ne 1 -or $socketMount[0].RW) {
    throw "Sandbox runner Docker socket boundary is missing or writable as a mount"
}

foreach ($service in @("api", "worker", "web")) {
    $containerId = docker compose ps --quiet $service
    if ($containerId) {
        $mounts = docker inspect $containerId --format "{{json .Mounts}}" | ConvertFrom-Json
        if (@($mounts | Where-Object { $_.Destination -eq "/var/run/docker.sock" }).Count -ne 0) {
            throw "$service unexpectedly received Docker Engine access"
        }
    }
}

$remaining = docker ps --all --quiet --filter "label=foundora.sandbox.managed=true"
if ($LASTEXITCODE -ne 0 -or $remaining) {
    throw "Runner probes left a managed child container behind"
}
$remainingVolumes = docker volume ls --quiet --filter "label=foundora.sandbox.managed=true"
if ($LASTEXITCODE -ne 0 -or $remainingVolumes) {
    throw "Runner probes left a managed source volume behind"
}

$orphanId = docker create `
    --label "foundora.sandbox.managed=true" `
    --label "foundora.sandbox.execution=90000000-0000-4000-8000-000000000009" `
    foundora-sandbox-runtime:phase22
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($orphanId)) {
    throw "Could not create the stopped janitor fixture"
}
$orphanVolume = "foundora-sandbox-source-90000000-0000-4000-8000-000000000009"
docker volume create `
    --label "foundora.sandbox.managed=true" `
    --label "foundora.sandbox.execution=90000000-0000-4000-8000-000000000009" `
    $orphanVolume | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the janitor volume fixture"
}
Invoke-Checked { docker compose restart sandbox-runner } "Sandbox runner restart failed"
$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Seconds 1
    $health = docker inspect $runnerId --format "{{if .State.Health}}{{.State.Health.Status}}{{end}}"
} while ($health -ne "healthy" -and (Get-Date) -lt $deadline)
if ($health -ne "healthy") {
    throw "Sandbox runner did not recover after restart"
}
$orphanRemaining = docker ps --all --quiet --filter "id=$orphanId"
if ($LASTEXITCODE -ne 0 -or $orphanRemaining) {
    throw "Startup janitor did not remove the orphaned child"
}
$orphanVolumeRemaining = docker volume ls --quiet --filter "name=$orphanVolume"
if ($LASTEXITCODE -ne 0 -or $orphanVolumeRemaining) {
    throw "Startup janitor did not remove the orphaned source volume"
}

Write-Output "Sandbox Phase 22 adversarial runner probes passed twice"
Write-Output "Runner token length: $($token.Length) (value not logged)"
