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
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/businesses"
    }
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/workspace"
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
    if (-not $webLoginResponse.Content.Contains("Choose your business context")) {
        throw "Owner login through the web form did not reach the protected workspace"
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

    $csrfCookie = $ownerSession.Cookies.GetCookies($smokeApiOrigin) | `
        Where-Object { $_.Name -eq "csrf" } | Select-Object -First 1
    $sessionCookie = $ownerSession.Cookies.GetCookies($smokeApiOrigin) | `
        Where-Object { $_.Name -eq "id" } | Select-Object -First 1
    if (-not $csrfCookie -or -not $sessionCookie) {
        throw "Authentication cookies were not retained"
    }
    $oldSessionToken = $sessionCookie.Value

    Assert-HttpStatus -ExpectedStatus 409 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/workspace" `
            -WebSession $ownerSession
    }
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/businesses" `
            -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = "" } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ name = "Rejected $runId"; summary = "Missing CSRF" } | ConvertTo-Json -Compress)
    }

    $businessAName = "Alpha $runId"
    $businessBName = "Beta $runId"
    $businessAResponse = Invoke-RestMethod -Uri "$smokeApiOrigin/businesses" `
        -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ name = $businessAName; summary = "Alpha-only profile" } | ConvertTo-Json -Compress)
    $businessAId = [string]$businessAResponse.id
    if (-not $businessAResponse.selected) {
        throw "The first business was not selected automatically"
    }

    $goalAResponse = Invoke-RestMethod -Uri "$smokeApiOrigin/workspace/goals" `
        -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ title = "Alpha-only goal"; details = "Must never appear in Beta"; target_date = $null } | ConvertTo-Json -Compress)
    if ($goalAResponse.title -ne "Alpha-only goal") { throw "Alpha goal was not created" }

    $businessBResponse = Invoke-RestMethod -Uri "$smokeApiOrigin/businesses" `
        -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ name = $businessBName; summary = "Beta-only profile" } | ConvertTo-Json -Compress)
    $businessBId = [string]$businessBResponse.id

    $stillAlpha = Invoke-RestMethod -Uri "$smokeApiOrigin/workspace" -WebSession $ownerSession
    if ($stillAlpha.business.id -ne $businessAId -or $stillAlpha.goals.Count -ne 1) {
        throw "Creating a second business changed or mixed the selected context"
    }

    Invoke-RestMethod -Uri "$smokeApiOrigin/businesses/select" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ business_id = $businessBId } | ConvertTo-Json -Compress) | Out-Null
    $betaWorkspace = Invoke-RestMethod -Uri "$smokeApiOrigin/workspace" -WebSession $ownerSession
    if ($betaWorkspace.business.id -ne $businessBId -or $betaWorkspace.business.summary -ne "Beta-only profile") {
        throw "Business switching did not resolve the Beta profile"
    }
    if ($betaWorkspace.goals.Count -ne 0) {
        throw "Alpha operational data leaked into the Beta workspace"
    }

    $preferencesResponse = Invoke-RestMethod -Uri "$smokeApiOrigin/workspace/preferences" `
        -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ timezone = "Asia/Kolkata"; currency = "INR"; locale = "en-IN" } | ConvertTo-Json -Compress)
    if ($preferencesResponse.currency -ne "INR") { throw "Business preferences were not updated" }

    $statusResponse = Invoke-RestMethod -Uri "$smokeApiOrigin/workspace/status" `
        -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ status = "active" } | ConvertTo-Json -Compress)
    if ($statusResponse.status -ne "active") { throw "Business status was not updated" }

    $goalBResponse = Invoke-RestMethod -Uri "$smokeApiOrigin/workspace/goals" `
        -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ title = "Beta-only goal"; details = "Must never appear in Alpha"; target_date = "2026-12-31" } | ConvertTo-Json -Compress)
    $goalBId = [string]$goalBResponse.id

    Invoke-RestMethod -Uri "$smokeApiOrigin/businesses/select" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ business_id = $businessAId } | ConvertTo-Json -Compress) | Out-Null
    $alphaWorkspace = Invoke-RestMethod -Uri "$smokeApiOrigin/workspace" -WebSession $ownerSession
    if ($alphaWorkspace.business.id -ne $businessAId -or $alphaWorkspace.goals.Count -ne 1) {
        throw "Switching back did not restore the isolated Alpha workspace"
    }
    if ($alphaWorkspace.goals[0].title -ne "Alpha-only goal") {
        throw "Beta goal leaked into the Alpha workspace"
    }
    Assert-HttpStatus -ExpectedStatus 404 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/workspace/goals/$goalBId/status" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ status = "completed" } | ConvertTo-Json -Compress)
    }

    $archiveResponse = Invoke-RestMethod -Uri "$smokeApiOrigin/workspace/archive" `
        -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -WebSession $ownerSession
    if ($archiveResponse.id -ne $businessAId -or -not $archiveResponse.archived_at) {
        throw "Selected business was not archived"
    }
    Assert-HttpStatus -ExpectedStatus 409 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/workspace" `
            -WebSession $ownerSession
    }
    Assert-HttpStatus -ExpectedStatus 404 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/businesses/select" `
            -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ business_id = $businessAId } | ConvertTo-Json -Compress)
    }
    Invoke-RestMethod -Uri "$smokeApiOrigin/businesses/select" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ business_id = $businessBId } | ConvertTo-Json -Compress) | Out-Null

    $workspacePage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/workspace" -WebSession $ownerWebSession
    if (-not $workspacePage.Content.Contains("Create another business")) {
        throw "Authenticated business workspace did not render"
    }
    $createFormMatch = [regex]::Match(
        $workspacePage.Content,
        '<form[^>]*>(?:(?!</form>)[\s\S])*?id="create-name"(?:(?!</form>)[\s\S])*?</form>'
    )
    if (-not $createFormMatch.Success) { throw "Business creation form was not rendered" }
    $createActionMatch = [regex]::Match(
        $createFormMatch.Value,
        'name="(?<name>\$ACTION_ID_[A-Za-z0-9]+)"'
    )
    if (-not $createActionMatch.Success) { throw "Business creation action was not rendered" }
    $webBusinessName = "Web $runId"
    $businessForm = @{ name = $webBusinessName; summary = "Created through the real web action" }
    $businessForm[$createActionMatch.Groups["name"].Value] = ""
    $businessBoundary = "foundora-business-$([guid]::NewGuid().ToString('N'))"
    $businessMultipart = [Text.StringBuilder]::new()
    foreach ($field in $businessForm.GetEnumerator()) {
        [void]$businessMultipart.Append("--$businessBoundary`r`n")
        [void]$businessMultipart.Append("Content-Disposition: form-data; name=`"$($field.Key)`"`r`n`r`n")
        [void]$businessMultipart.Append("$($field.Value)`r`n")
    }
    [void]$businessMultipart.Append("--$businessBoundary--`r`n")
    $businessMultipartBytes = [Text.Encoding]::UTF8.GetBytes($businessMultipart.ToString())
    $webBusinessResponse = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/workspace" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin } `
        -ContentType "multipart/form-data; boundary=$businessBoundary" `
        -Body $businessMultipartBytes -WebSession $ownerWebSession
    if (-not $webBusinessResponse.Content.Contains($webBusinessName)) {
        throw "Business creation through the web action did not select its workspace"
    }
    $apiSessionStillBeta = Invoke-RestMethod -Uri "$smokeApiOrigin/workspace" `
        -WebSession $ownerSession
    if ($apiSessionStillBeta.business.id -ne $businessBId) {
        throw "Business selection leaked between independent owner sessions"
    }

    $settingsPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/settings/security" -WebSession $ownerWebSession
    if (-not $settingsPage.Content.Contains("Owner settings")) {
        throw "Authenticated security settings did not render"
    }

    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/auth/sessions/revoke-others" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = "" } `
            -WebSession $ownerSession
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
    if ($LASTEXITCODE -ne 0 -or $smokeVersion.Trim() -ne "20260822_03") {
        throw "Isolated Phase 03 migration is not current"
    }
    $ownerCount = docker compose exec -T postgres psql -U foundora -d $smokeDatabase `
        -tAc "SELECT count(*) FROM owners WHERE singleton_key = 1 AND position('argon2id' in password_hash) = 2"
    if ($LASTEXITCODE -ne 0 -or $ownerCount.Trim() -ne "1") {
        throw "Exactly one Argon2id owner credential was not found"
    }
    $businessCount = docker compose exec -T postgres psql -U foundora -d $smokeDatabase `
        -tAc "SELECT count(*) FROM businesses"
    if ($LASTEXITCODE -ne 0 -or $businessCount.Trim() -ne "3") {
        throw "Expected three isolated smoke businesses"
    }
    $crossBusinessGoalCount = docker compose exec -T postgres psql -U foundora -d $smokeDatabase `
        -tAc "SELECT count(*) FROM business_goals g JOIN businesses b ON b.id = g.business_id WHERE (b.name = '$businessAName' AND g.title = 'Beta-only goal') OR (b.name = '$businessBName' AND g.title = 'Alpha-only goal')"
    if ($LASTEXITCODE -ne 0 -or $crossBusinessGoalCount.Trim() -ne "0") {
        throw "Goal persistence crossed a business boundary"
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
    $businessForm = $null
    $businessMultipart = $null
    $businessMultipartBytes = $null
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
if ($LASTEXITCODE -ne 0 -or $migrationVersion.Trim() -ne "20260822_03") {
    throw "Phase 03 migration is not current"
}
Invoke-Checked { docker compose exec -T worker python -m foundora.worker_health }

Invoke-Checked { docker compose ps }
