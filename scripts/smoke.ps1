$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

function New-RandomPassword {
    $bytes = New-Object byte[] 24
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
        return [Convert]::ToBase64String($bytes)
    }
    finally {
        $generator.Dispose()
        [Array]::Clear($bytes, 0, $bytes.Length)
    }
}

function Assert-HttpStatus {
    param(
        [scriptblock]$Request,
        [int]$ExpectedStatus
    )
    try {
        $response = & $Request
        $actualStatus = [int]$response.StatusCode
    }
    catch {
        if (-not $_.Exception.Response) { throw }
        $actualStatus = [int]$_.Exception.Response.StatusCode
    }
    if ($actualStatus -ne $ExpectedStatus) {
        throw "Expected HTTP $ExpectedStatus but received HTTP $actualStatus"
    }
}

function Wait-ForHttp {
    param(
        [string]$Uri,
        [int]$Attempts = 30
    )
    foreach ($attempt in 1..$Attempts) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return }
        }
        catch {
            if ($attempt -eq $Attempts) { throw }
        }
        Start-Sleep -Seconds 1
    }
    throw "HTTP endpoint did not become available: $Uri"
}

Invoke-Checked { docker compose up --build --detach --wait }

$apiPort = if ($env:API_PORT) { $env:API_PORT } else { "8000" }
$webPort = if ($env:WEB_PORT) { $env:WEB_PORT } else { "3000" }
$apiOrigin = "http://localhost:$apiPort"
$publicOrigin = "http://localhost:$webPort"

$readiness = Invoke-RestMethod -Uri "$apiOrigin/health/ready"
if ($readiness.status -ne "ready") { throw "API readiness did not report ready" }

Assert-HttpStatus -ExpectedStatus 401 -Request {
    Invoke-WebRequest -UseBasicParsing -Uri "$apiOrigin/auth/session"
}

$mainLoginPage = Invoke-WebRequest -UseBasicParsing -Uri "$publicOrigin/login"
if ($mainLoginPage.StatusCode -ne 200 -or -not $mainLoginPage.Content.Contains("FOUNDORA / OWNER ACCESS")) {
    throw "Public login page did not render"
}

$authApiPort = if ($env:AUTH_SMOKE_API_PORT) { $env:AUTH_SMOKE_API_PORT } else { "18000" }
$authWebPort = if ($env:AUTH_SMOKE_WEB_PORT) { $env:AUTH_SMOKE_WEB_PORT } else { "13000" }
$runId = ([guid]::NewGuid().ToString("N")).Substring(0, 12)
$smokeDatabase = "foundora_smoke_$runId"
$smokeApiContainer = "foundora-auth-smoke-$runId"
$smokeWebContainer = "foundora-web-smoke-$runId"
$smokeApiOrigin = "http://localhost:$authApiPort"
$smokePublicOrigin = "http://localhost:$authWebPort"
$smokeDatabaseUrl = "postgresql+asyncpg://foundora@postgres:5432/$smokeDatabase"
$smokePassword = New-RandomPassword
$replacementPassword = New-RandomPassword
$ownerEmail = "owner-$runId@foundora.local"
$rateLimitEmail = "rate-$runId@foundora.local"
$smokeDatabaseCreated = $false

try {
    Invoke-Checked { docker compose exec -T postgres createdb -U foundora $smokeDatabase }
    $smokeDatabaseCreated = $true
    Invoke-Checked { docker compose exec -T redis redis-cli -n 1 FLUSHDB }
    Invoke-Checked {
        docker compose run --rm --no-deps `
            -e FOUNDORA_DATABASE_URL=$smokeDatabaseUrl migrate
    }
    Invoke-Checked {
        docker compose run --detach --no-deps --name $smokeApiContainer `
            --publish "127.0.0.1:${authApiPort}:8000" `
            -e FOUNDORA_DATABASE_URL=$smokeDatabaseUrl `
            -e FOUNDORA_REDIS_URL=redis://redis:6379/1 `
            -e FOUNDORA_PUBLIC_ORIGIN=$smokePublicOrigin api
    }
    Invoke-Checked {
        docker compose run --detach --no-deps --name $smokeWebContainer `
            --publish "127.0.0.1:${authWebPort}:3000" `
            -e API_INTERNAL_URL=http://${smokeApiContainer}:8000 `
            -e FOUNDORA_PUBLIC_ORIGIN=$smokePublicOrigin web
    }

    Wait-ForHttp -Uri "$smokeApiOrigin/health/ready"
    Wait-ForHttp -Uri "$smokePublicOrigin/login"

    Invoke-Checked {
        docker exec -e FOUNDORA_SMOKE_OWNER_PASSWORD=$smokePassword $smokeApiContainer `
            python -m foundora.owner --email $ownerEmail `
            --password-env FOUNDORA_SMOKE_OWNER_PASSWORD
    }

    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/auth/session"
    }

    $rateLimitBody = @{ email = $rateLimitEmail; password = $smokePassword } | `
        ConvertTo-Json -Compress
    foreach ($attempt in 1..5) {
        Assert-HttpStatus -ExpectedStatus 401 -Request {
            Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/auth/login" -Method Post `
                -Headers @{ Origin = $smokePublicOrigin } -ContentType "application/json" `
                -Body $rateLimitBody
        }
    }
    Assert-HttpStatus -ExpectedStatus 429 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/auth/login" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin } -ContentType "application/json" `
            -Body $rateLimitBody
    }

    $loginPage = Invoke-WebRequest -UseBasicParsing -Uri "$smokePublicOrigin/login"
    $actionMatch = [regex]::Match(
        $loginPage.Content,
        'name="(?<name>\$ACTION_ID_[A-Za-z0-9]+)"'
    )
    if (-not $actionMatch.Success) { throw "Owner login form action was not rendered" }
    $loginForm = @{ email = $ownerEmail; password = $smokePassword }
    $loginForm[$actionMatch.Groups["name"].Value] = ""
    $boundary = "foundora-$([guid]::NewGuid().ToString('N'))"
    $multipart = [Text.StringBuilder]::new()
    foreach ($field in $loginForm.GetEnumerator()) {
        [void]$multipart.Append("--$boundary`r`n")
        [void]$multipart.Append("Content-Disposition: form-data; name=`"$($field.Key)`"`r`n`r`n")
        [void]$multipart.Append("$($field.Value)`r`n")
    }
    [void]$multipart.Append("--$boundary--`r`n")
    $multipartBytes = [Text.Encoding]::UTF8.GetBytes($multipart.ToString())
    $webLoginResponse = Invoke-WebRequest -UseBasicParsing -Uri "$smokePublicOrigin/login" `
        -Method Post -Headers @{ Origin = $smokePublicOrigin } `
        -ContentType "multipart/form-data; boundary=$boundary" -Body $multipartBytes `
        -SessionVariable ownerWebSession
    if (-not $webLoginResponse.Content.Contains("Owner settings")) {
        throw "Owner login through the web form did not reach protected settings"
    }

    $loginBody = @{ email = $ownerEmail; password = $smokePassword } | ConvertTo-Json -Compress
    $loginResponse = Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/auth/login" `
        -Method Post -Headers @{ Origin = $smokePublicOrigin } -ContentType "application/json" `
        -Body $loginBody -SessionVariable ownerSession
    if ($loginResponse.StatusCode -ne 200) { throw "Owner login failed" }
    $setCookie = [string]$loginResponse.Headers["Set-Cookie"]
    if (-not ($setCookie.Contains("HttpOnly") -and $setCookie.Contains("SameSite=strict"))) {
        throw "Authentication cookies are missing required security attributes"
    }

    $sessionResponse = Invoke-RestMethod -Uri "$smokeApiOrigin/auth/session" `
        -WebSession $ownerSession
    if ($sessionResponse.owner.email -ne $ownerEmail) {
        throw "Authenticated owner identity mismatch"
    }

    $settingsPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/settings/security" -WebSession $ownerWebSession
    if (-not $settingsPage.Content.Contains("Owner settings")) {
        throw "Authenticated security settings did not render"
    }

    $csrfCookie = $ownerSession.Cookies.GetCookies($smokeApiOrigin) | `
        Where-Object { $_.Name -eq "csrf" } | Select-Object -First 1
    $sessionCookie = $ownerSession.Cookies.GetCookies($smokeApiOrigin) | `
        Where-Object { $_.Name -eq "id" } | Select-Object -First 1
    if (-not $csrfCookie -or -not $sessionCookie) {
        throw "Authentication cookies were not retained"
    }
    $oldSessionToken = $sessionCookie.Value

    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/auth/sessions/revoke-others" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin } -WebSession $ownerSession
    }

    $passwordBody = @{
        current_password = $smokePassword
        new_password = $replacementPassword
    } | ConvertTo-Json -Compress
    $passwordResponse = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokeApiOrigin/auth/password" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -Body $passwordBody -WebSession $ownerSession
    if ($passwordResponse.StatusCode -ne 200) { throw "Owner password change failed" }

    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/auth/session" `
            -Headers @{ Cookie = "id=$oldSessionToken" }
    }
    $revokedWebSession = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/settings/security" -WebSession $ownerWebSession
    if (-not $revokedWebSession.Content.Contains("FOUNDORA / OWNER ACCESS")) {
        throw "Password rotation did not block the previous web session"
    }

    $csrfCookie = $ownerSession.Cookies.GetCookies($smokeApiOrigin) | `
        Where-Object { $_.Name -eq "csrf" } | Select-Object -First 1
    $logoutResponse = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokeApiOrigin/auth/logout" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -WebSession $ownerSession
    if ($logoutResponse.StatusCode -ne 204) { throw "Owner logout failed" }

    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/auth/session" `
            -WebSession $ownerSession
    }

    $smokeVersion = docker compose exec -T postgres psql -U foundora -d $smokeDatabase `
        -tAc "SELECT version_num FROM alembic_version"
    if ($LASTEXITCODE -ne 0 -or $smokeVersion.Trim() -ne "20260822_02") {
        throw "Isolated Phase 02 migration is not current"
    }
    $ownerCount = docker compose exec -T postgres psql -U foundora -d $smokeDatabase `
        -tAc "SELECT count(*) FROM owners WHERE singleton_key = 1 AND position('argon2id' in password_hash) = 2"
    if ($LASTEXITCODE -ne 0 -or $ownerCount.Trim() -ne "1") {
        throw "Exactly one Argon2id owner credential was not found"
    }
}
finally {
    if ($smokeWebContainer) {
        docker rm --force $smokeWebContainer 2>$null | Out-Null
    }
    if ($smokeApiContainer) {
        docker rm --force $smokeApiContainer 2>$null | Out-Null
    }
    if ($smokeDatabaseCreated) {
        docker compose exec -T postgres dropdb --force --if-exists -U foundora $smokeDatabase `
            2>$null | Out-Null
    }
    docker compose exec -T redis redis-cli -n 1 FLUSHDB 2>$null | Out-Null
    $smokePassword = $null
    $replacementPassword = $null
    $loginBody = $null
    $passwordBody = $null
    $rateLimitBody = $null
    $loginForm = $null
    $multipart = $null
    $multipartBytes = $null
    $rateLimitEmail = $null
    $oldSessionToken = $null
}

$webResponse = Invoke-WebRequest -UseBasicParsing -Uri "$publicOrigin/login"
if ($webResponse.StatusCode -ne 200) { throw "Frontend did not return HTTP 200" }
$securityHeaders = @(
    "Content-Security-Policy",
    "Referrer-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options"
)
foreach ($header in $securityHeaders) {
    if (-not $webResponse.Headers[$header]) { throw "Frontend security header missing: $header" }
}
$apiHeaderResponse = Invoke-WebRequest -UseBasicParsing -Uri "$apiOrigin/health/live"
foreach ($header in $securityHeaders) {
    if (-not $apiHeaderResponse.Headers[$header]) { throw "API security header missing: $header" }
}

Invoke-Checked { docker compose exec -T postgres pg_isready -U foundora -d foundora }
Invoke-Checked { docker compose exec -T redis redis-cli ping }
$migrationVersion = docker compose exec -T postgres psql -U foundora -d foundora -tAc `
    "SELECT version_num FROM alembic_version"
if ($LASTEXITCODE -ne 0 -or $migrationVersion.Trim() -ne "20260822_02") {
    throw "Phase 02 migration is not current"
}
Invoke-Checked { docker compose exec -T worker python -m foundora.worker_health }

Invoke-Checked { docker compose ps }
