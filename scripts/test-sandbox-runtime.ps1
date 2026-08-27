param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $workspace "apps/sandbox-runtime"
$image = "foundora-sandbox-runtime:slice0"
$manifestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $runtimeRoot "runtime-manifest.json")).Hash.ToLowerInvariant()
$manifest = Get-Content -LiteralPath (Join-Path $runtimeRoot "runtime-manifest.json") -Raw | ConvertFrom-Json
$seccompPath = Join-Path $runtimeRoot "seccomp-profile.json"
$seccompHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $seccompPath).Hash.ToLowerInvariant()

if ($manifestHash -ne "ab73f13726b30608c83a212d7cf762ee2b74986f535680377560db69286d8601") {
    throw "Sandbox runtime manifest digest does not match static-website@1"
}
if ($seccompHash -ne $manifest.seccomp_profile_sha256) {
    throw "Sandbox seccomp profile digest does not match the runtime manifest"
}

if (-not $SkipBuild) {
    docker build --tag $image $runtimeRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Sandbox runtime image build failed"
    }
}

$workspaceMount = "type=bind,source=$workspace,target=/workspace,readonly"
docker run --rm --entrypoint node --mount $workspaceMount -w /workspace $image `
    --test --test-isolation=none apps/sandbox-runtime/contract.test.mjs
if ($LASTEXITCODE -ne 0) {
    throw "Sandbox runtime contract tests failed"
}

npm audit --prefix $runtimeRoot --audit-level=high --package-lock-only
if ($LASTEXITCODE -ne 0) {
    throw "Sandbox runtime dependency audit failed"
}

$imageConfigJson = docker image inspect $image --format "{{json .Config}}"
if ($LASTEXITCODE -ne 0) {
    throw "Sandbox runtime image inspection failed"
}
$imageConfig = $imageConfigJson | ConvertFrom-Json
if ($imageConfig.User -ne "pwuser") {
    throw "Sandbox runtime image is not pinned to pwuser"
}
if (($imageConfig.Entrypoint -join " ") -ne "node /opt/foundora/runtime/runtime.mjs") {
    throw "Sandbox runtime image entrypoint is not fixed"
}
if ($imageConfig.Labels.'org.foundora.sandbox.build-manifest-sha256' -ne $manifestHash) {
    throw "Sandbox runtime image label does not match the build manifest"
}
$forbiddenEnvironment = $imageConfig.Env | Where-Object {
    $_ -match '^(OPENAI_API_KEY|GEMINI_API_KEY|ANTHROPIC_API_KEY|FOUNDORA_DATABASE_URL|FOUNDORA_REDIS_URL)='
}
if ($forbiddenEnvironment) {
    throw "Sandbox runtime image contains an application or provider credential variable"
}

function Invoke-SandboxFixture {
    param(
        [Parameter(Mandatory = $true)][string]$Fixture,
        [string]$InputFile = "routes-root.json",
        [Parameter(Mandatory = $true)][int]$ExpectedExitCode
    )

    $fixturePath = Join-Path $runtimeRoot "fixtures/$Fixture"
    $inputPath = Join-Path $runtimeRoot "fixtures/input/$InputFile"
    $arguments = @(
        "run", "--rm", "--init",
        "--label", "foundora.sandbox.slice0=true",
        "--network", "none",
        "--cpus", "1",
        "--memory", "512m",
        "--memory-swap", "512m",
        "--pids-limit", "128",
        "--read-only",
        "--cap-drop", "ALL",
        "--cap-add", "SYS_CHROOT",
        "--security-opt", "no-new-privileges:true",
        "--security-opt", "seccomp=$seccompPath",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=134217728",
        "--tmpfs", "/dev/shm:rw,noexec,nosuid,nodev,size=134217728",
        "--mount", "type=bind,source=$fixturePath,target=/site,readonly",
        "--mount", "type=bind,source=$inputPath,target=/foundora-input/routes.json,readonly",
        $image
    )
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & docker @arguments 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($exitCode -ne $ExpectedExitCode) {
        throw "Fixture $Fixture exited $exitCode instead of $ExpectedExitCode`: $($output -join ' ')"
    }
    return $output -join "`n"
}

$passing = Invoke-SandboxFixture -Fixture "passing" -ExpectedExitCode 0 | ConvertFrom-Json
if ($passing.status -ne "passed" -or
        $passing.route_results.Count -ne 1 -or
        -not $passing.route_results[0].execution_marker) {
    throw "Passing fixture did not prove generated JavaScript execution"
}

$javascriptFailure = Invoke-SandboxFixture -Fixture "javascript-error" -ExpectedExitCode 1 | ConvertFrom-Json
if ($javascriptFailure.status -ne "failed" -or
        $javascriptFailure.route_results[0].runtime_errors.Count -lt 1) {
    throw "JavaScript failure fixture was not reported honestly"
}

$networkFailure = Invoke-SandboxFixture -Fixture "network" -ExpectedExitCode 1 | ConvertFrom-Json
if ($networkFailure.status -ne "failed" -or
        ($networkFailure.route_results[0].runtime_errors -join " ") -notmatch "blocked external request") {
    throw "Network fixture was not blocked and reported"
}

$timeoutFailure = Invoke-SandboxFixture -Fixture "timeout" -ExpectedExitCode 1 | ConvertFrom-Json
if ($timeoutFailure.status -ne "failed" -or
        ($timeoutFailure.route_results[0].runtime_errors -join " ") -notmatch "Timeout") {
    throw "Route timeout fixture was not bounded and reported"
}

$outputFailure = Invoke-SandboxFixture -Fixture "output" -ExpectedExitCode 1 | ConvertFrom-Json
$maximumErrorLength = ($outputFailure.route_results[0].runtime_errors |
        Measure-Object -Property Length -Maximum).Maximum
if ($outputFailure.status -ne "failed" -or
        $outputFailure.route_results[0].runtime_errors.Count -ne 32 -or
        $maximumErrorLength -gt 500) {
    throw "Untrusted browser output was not bounded by the harness contract"
}

$invalidInput = Invoke-SandboxFixture -Fixture "passing" -InputFile "routes-extra-field.json" -ExpectedExitCode 2
if ($invalidInput -notmatch "does not match contract version 1") {
    throw "Unknown route-input fields were not rejected"
}

$remaining = docker ps --all --quiet --filter "label=foundora.sandbox.slice0=true"
if ($LASTEXITCODE -ne 0 -or $remaining) {
    throw "Slice 0 probe left a labeled child container behind"
}

$imageId = docker image inspect $image --format "{{.Id}}"
Write-Output "Sandbox Slice 0 runtime probes passed"
Write-Output "Image: $imageId"
Write-Output "Manifest: $manifestHash"
Write-Output "Seccomp: $seccompHash"
