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
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/onboarding"
    }
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/ai"
    }
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/brain/context"
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

    $newOnboarding = Invoke-RestMethod -Uri "$smokeApiOrigin/onboarding" `
        -WebSession $ownerSession
    if ($newOnboarding.business_id -ne $businessAId -or `
            $newOnboarding.draft.revision -ne 0 -or `
            $newOnboarding.draft.status -ne "draft" -or `
            $newOnboarding.approved_profile) {
        throw "New Alpha onboarding did not start as an unapproved resumable draft"
    }

    $foundationResponse = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/onboarding/steps/foundation" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            revision = 0
            business_type = "idea"
            business_name = $businessAName
            industry = "Founder software"
            geography = "India"
        } | ConvertTo-Json -Compress)
    if ($foundationResponse.revision -ne 1 -or $foundationResponse.current_step -ne 2) {
        throw "Onboarding foundation step was not saved resumably"
    }
    Assert-HttpStatus -ExpectedStatus 409 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/onboarding/steps/market" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                revision = 0
                problem = "Stale problem"
                target_audience = "Stale audience"
                offer = "Stale offer"
            } | ConvertTo-Json -Compress)
    }
    Assert-HttpStatus -ExpectedStatus 422 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/onboarding/submit" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ revision = 1 } | ConvertTo-Json -Compress)
    }

    $marketResponse = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/onboarding/steps/market" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            revision = 1
            problem = "Founders lose time coordinating fragmented launch work"
            target_audience = "First-time founders in India"
            offer = "An approved launch operating profile"
        } | ConvertTo-Json -Compress)
    if ($marketResponse.revision -ne 2 -or $marketResponse.current_step -ne 3) {
        throw "Onboarding market step was not saved"
    }

    $executionResponse = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/onboarding/steps/execution" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            revision = 2
            goals = @("Launch an approved profile", "Reach ten founders")
            existing_assets = @("Founder domain")
            constraints = @("Small team", "No autonomous spend")
            budget = "Founder-declared INR 100,000 launch ceiling"
        } | ConvertTo-Json -Depth 4 -Compress)
    if ($executionResponse.revision -ne 3 -or $executionResponse.goals.Count -ne 2) {
        throw "Onboarding execution step was not saved"
    }

    $brandResponse = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/onboarding/steps/brand-services" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            revision = 3
            brand_preferences = "Direct, calm, and evidence-led"
            connected_services = @("GitHub", "Google Workspace")
        } | ConvertTo-Json -Depth 4 -Compress)
    if ($brandResponse.revision -ne 4 -or $brandResponse.current_step -ne 5) {
        throw "Onboarding brand and services step was not saved"
    }

    $resumedDraft = Invoke-RestMethod -Uri "$smokeApiOrigin/onboarding" `
        -WebSession $ownerSession
    if ($resumedDraft.draft.revision -ne 4 -or `
            $resumedDraft.draft.problem -ne "Founders lose time coordinating fragmented launch work" -or `
            $resumedDraft.approved_profile) {
        throw "Saved onboarding draft was not resumable or was silently approved"
    }
    Assert-HttpStatus -ExpectedStatus 409 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/onboarding/approve" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ revision = 4 } | ConvertTo-Json -Compress)
    }

    $reviewResponse = Invoke-RestMethod -Uri "$smokeApiOrigin/onboarding/submit" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ revision = 4 } | ConvertTo-Json -Compress)
    if ($reviewResponse.status -ne "review" -or $reviewResponse.revision -ne 5) {
        throw "Onboarding was not frozen for separate founder review"
    }
    Assert-HttpStatus -ExpectedStatus 409 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/onboarding/steps/market" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                revision = 5
                problem = "Review mutation"
                target_audience = "Review mutation"
                offer = "Review mutation"
            } | ConvertTo-Json -Compress)
    }

    $approvedProfile = Invoke-RestMethod -Uri "$smokeApiOrigin/onboarding/approve" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ revision = 5 } | ConvertTo-Json -Compress)
    if ($approvedProfile.version -ne 1 -or `
            $approvedProfile.offer -ne "An approved launch operating profile") {
        throw "Founder approval did not create the exact version-one profile"
    }

    $reopenResponse = Invoke-RestMethod -Uri "$smokeApiOrigin/onboarding/reopen" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ revision = 6 } | ConvertTo-Json -Compress)
    if ($reopenResponse.status -ne "draft" -or $reopenResponse.revision -ne 7) {
        throw "Approved onboarding could not be reopened as a revision draft"
    }

    $revisedMarket = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/onboarding/steps/market" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            revision = 7
            problem = "Founders lose time coordinating fragmented launch work"
            target_audience = "First-time founders in India"
            offer = "A revised founder-approved operating profile"
        } | ConvertTo-Json -Compress)
    if ($revisedMarket.revision -ne 8) { throw "Onboarding revision was not saved" }
    $unapprovedRevision = Invoke-RestMethod -Uri "$smokeApiOrigin/onboarding" `
        -WebSession $ownerSession
    if ($unapprovedRevision.approved_profile.version -ne 1 -or `
            $unapprovedRevision.approved_profile.offer -ne "An approved launch operating profile" -or `
            $unapprovedRevision.draft.offer -ne "A revised founder-approved operating profile") {
        throw "Unapproved revision silently changed the approved business facts"
    }

    $secondReview = Invoke-RestMethod -Uri "$smokeApiOrigin/onboarding/submit" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ revision = 8 } | ConvertTo-Json -Compress)
    $secondApproval = Invoke-RestMethod -Uri "$smokeApiOrigin/onboarding/approve" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ revision = $secondReview.revision } | ConvertTo-Json -Compress)
    if ($secondApproval.version -ne 2 -or `
            $secondApproval.offer -ne "A revised founder-approved operating profile") {
        throw "Explicit reapproval did not create exact profile version two"
    }

    $staleGoalTitle = "Completed context goal $runId"
    $staleGoal = Invoke-RestMethod -Uri "$smokeApiOrigin/workspace/goals" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            title = $staleGoalTitle
            details = "Must be excluded as stale context"
            target_date = $null
        } | ConvertTo-Json -Compress)
    Invoke-RestMethod `
        -Uri "$smokeApiOrigin/workspace/goals/$($staleGoal.id)/status" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ status = "completed" } | ConvertTo-Json -Compress) | Out-Null

    $invalidatedGoalTitle = "Cancelled context goal $runId"
    $invalidatedGoal = Invoke-RestMethod -Uri "$smokeApiOrigin/workspace/goals" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            title = $invalidatedGoalTitle
            details = "Must be excluded as invalidated context"
            target_date = $null
        } | ConvertTo-Json -Compress)
    Invoke-RestMethod `
        -Uri "$smokeApiOrigin/workspace/goals/$($invalidatedGoal.id)/status" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ status = "cancelled" } | ConvertTo-Json -Compress) | Out-Null

    $alphaBrain = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/brain/context?purpose=planning&token_budget=4096" `
        -WebSession $ownerSession
    $alphaContext = [string]$alphaBrain.context
    if ($alphaBrain.business_id -ne $businessAId -or `
            $alphaBrain.estimated_tokens -gt $alphaBrain.token_budget -or `
            -not $alphaContext.Contains("A revised founder-approved operating profile") -or `
            -not $alphaContext.Contains("Alpha-only goal") -or `
            $alphaContext.Contains("Beta-only goal") -or `
            $alphaContext.Contains($staleGoalTitle) -or `
            $alphaContext.Contains($invalidatedGoalTitle) -or `
            ([string]$alphaBrain.context_sha256).Length -ne 64) {
        throw "Alpha business context was not isolated, budgeted, or source-correct"
    }
    $staleDecision = $alphaBrain.sources | `
        Where-Object { $_.source_reference -eq "business_goals/$($staleGoal.id)" } | `
        Select-Object -First 1
    $invalidatedDecision = $alphaBrain.sources | `
        Where-Object { $_.source_reference -eq "business_goals/$($invalidatedGoal.id)" } | `
        Select-Object -First 1
    if ($staleDecision.exclusion_reason -ne "stale" -or `
            $staleDecision.content -or `
            $invalidatedDecision.exclusion_reason -ne "invalidated" -or `
            $invalidatedDecision.content) {
        throw "Stale or invalidated context sources were not safely excluded"
    }
    if (-not $alphaBrain.unavailable_sources.knowledge -or `
            -not $alphaBrain.unavailable_sources.current_tasks) {
        throw "Unavailable future context sources were not disclosed"
    }

    $profileOnlyBrain = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/brain/context?purpose=planning&token_budget=4096&sources=business_profile" `
        -WebSession $ownerSession
    if (([string]$profileOnlyBrain.context).Contains(
            "A revised founder-approved operating profile"
        ) -or `
            -not ($profileOnlyBrain.sources | Where-Object {
                    $_.source_type -eq "approved_profile" -and `
                    $_.exclusion_reason -eq "not_selected"
                })) {
        throw "Explicit business context source selection was not enforced"
    }
    $tightBrain = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/brain/context?purpose=planning&token_budget=256" `
        -WebSession $ownerSession
    if ($tightBrain.estimated_tokens -gt 256 -or `
            -not ($tightBrain.sources | Where-Object {
                    $_.exclusion_reason -eq "token_budget"
                })) {
        throw "Business context token ceiling was not enforced"
    }

    Invoke-RestMethod -Uri "$smokeApiOrigin/businesses/select" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ business_id = $businessBId } | ConvertTo-Json -Compress) | Out-Null
    $betaOnboarding = Invoke-RestMethod -Uri "$smokeApiOrigin/onboarding" `
        -WebSession $ownerSession
    if ($betaOnboarding.business_id -ne $businessBId -or `
            $betaOnboarding.draft.revision -ne 0 -or `
            $betaOnboarding.approved_profile) {
        throw "Alpha onboarding facts leaked into the Beta business"
    }
    $betaBrain = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/brain/context?purpose=planning&token_budget=4096" `
        -WebSession $ownerSession
    if ($betaBrain.business_id -ne $businessBId -or `
            ([string]$betaBrain.context).Contains("Alpha-only goal") -or `
            ([string]$betaBrain.context).Contains(
                "A revised founder-approved operating profile"
            ) -or `
            -not ([string]$betaBrain.context).Contains("Beta-only goal") -or `
            -not $betaBrain.unavailable_sources.approved_profile) {
        throw "Business brain context or availability crossed the selected business boundary"
    }
    Invoke-RestMethod -Uri "$smokeApiOrigin/businesses/select" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ business_id = $businessAId } | ConvertTo-Json -Compress) | Out-Null

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

    $gatewayDashboard = Invoke-RestMethod -Uri "$smokeApiOrigin/ai" `
        -WebSession $ownerSession
    $openAiStatus = $gatewayDashboard.providers | `
        Where-Object { $_.name -eq "openai" } | Select-Object -First 1
    $geminiStatus = $gatewayDashboard.providers | `
        Where-Object { $_.name -eq "gemini" } | Select-Object -First 1
    $anthropicStatus = $gatewayDashboard.providers | `
        Where-Object { $_.name -eq "anthropic" } | Select-Object -First 1
    if (-not $openAiStatus.configured -or -not $geminiStatus.configured) {
        throw "OpenAI and Gemini keys were not detected by the isolated API"
    }
    if ($anthropicStatus.configured) {
        throw "Anthropic unexpectedly reported configured without a supplied key"
    }
    if ($gatewayDashboard.usage.calls -ne 0) {
        throw "Fresh business model usage was not isolated"
    }

    $openAiValidation = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/ai/providers/openai/validate" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -WebSession $ownerSession
    if (-not $openAiValidation.configured) {
        throw "Configured OpenAI credential was not validated"
    }
    $geminiValidation = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/ai/providers/gemini/validate" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -WebSession $ownerSession
    if (-not $geminiValidation.configured -or -not $geminiValidation.valid -or `
            -not $geminiValidation.model_available) {
        throw "Live Gemini provider validation failed"
    }
    $disabledValidation = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/ai/providers/anthropic/validate" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -WebSession $ownerSession
    if ($disabledValidation.configured -or $disabledValidation.valid -or `
            $disabledValidation.model_available) {
        throw "Missing Anthropic key did not disable the provider cleanly"
    }

    $liveGatewayBody = @{
        task_type = "acceptance"
        prompt = "Reply with exactly: FOUNDORA_GATEWAY_OK"
        sensitivity = "standard"
        allow_fallback = $true
        max_output_tokens = 32
        token_budget = 1024
        cost_budget_microusd = 2000
    } | ConvertTo-Json -Compress
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/ai/generate" `
            -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = "" } `
            -ContentType "application/json" -WebSession $ownerSession -Body $liveGatewayBody
    }
    Assert-HttpStatus -ExpectedStatus 422 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/ai/generate" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                task_type = "acceptance"
                prompt = "This must stop before execution"
                sensitivity = "standard"
                allow_fallback = $false
                max_output_tokens = 32
                token_budget = 10
                cost_budget_microusd = 2000
            } | ConvertTo-Json -Compress)
    }
    Assert-HttpStatus -ExpectedStatus 422 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/ai/generate" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                task_type = "acceptance"
                prompt = "Fallback policy rejection"
                sensitivity = "sensitive"
                allow_fallback = $true
                max_output_tokens = 32
                token_budget = 1024
                cost_budget_microusd = 2000
            } | ConvertTo-Json -Compress)
    }
    $liveGatewayResponse = Invoke-RestMethod -Uri "$smokeApiOrigin/ai/generate" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession -Body $liveGatewayBody
    if ([string]::IsNullOrWhiteSpace($liveGatewayResponse.text) -or `
            $liveGatewayResponse.provider -notin @("openai", "gemini") -or `
            $liveGatewayResponse.total_tokens -le 0 -or `
            $liveGatewayResponse.estimated_cost_microusd -gt 2000) {
        throw "Budgeted live model request did not return valid accounted output"
    }
    if ($liveGatewayResponse.provider -eq "openai" -and -not $openAiValidation.valid) {
        throw "Live request reported success from an invalid OpenAI configuration"
    }
    if (-not $openAiValidation.valid -and `
            ($liveGatewayResponse.provider -ne "gemini" -or `
                -not $liveGatewayResponse.fallback_used)) {
        throw "Invalid OpenAI primary did not fall back to validated Gemini"
    }
    $persistedGatewayDashboard = Invoke-RestMethod -Uri "$smokeApiOrigin/ai" `
        -WebSession $ownerSession
    if ($persistedGatewayDashboard.usage.calls -ne 1 -or `
            $persistedGatewayDashboard.usage.total_tokens -le 0 -or `
            $persistedGatewayDashboard.recent_calls.Count -lt 1) {
        throw "Successful live model usage was not persisted"
    }

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

    $webOnboardingPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/onboarding" -WebSession $ownerWebSession
    if (-not $webOnboardingPage.Content.Contains("Business starting point")) {
        throw "Protected resumable onboarding wizard did not render"
    }
    $foundationFormMatch = [regex]::Match(
        $webOnboardingPage.Content,
        '<form[^>]*>(?:(?!</form>)[\s\S])*?id="onboarding-name"(?:(?!</form>)[\s\S])*?</form>'
    )
    if (-not $foundationFormMatch.Success) { throw "Onboarding foundation form was not rendered" }
    $foundationActionMatch = [regex]::Match(
        $foundationFormMatch.Value,
        'name="(?<name>\$ACTION_ID_[A-Za-z0-9]+)"'
    )
    if (-not $foundationActionMatch.Success) { throw "Onboarding server action was not rendered" }
    $foundationForm = @{
        revision = "0"
        business_type = "existing"
        business_name = $webBusinessName
        industry = "Founder services"
        geography = "Remote"
    }
    $foundationForm[$foundationActionMatch.Groups["name"].Value] = ""
    $foundationBoundary = "foundora-onboarding-$([guid]::NewGuid().ToString('N'))"
    $foundationMultipart = [Text.StringBuilder]::new()
    foreach ($field in $foundationForm.GetEnumerator()) {
        [void]$foundationMultipart.Append("--$foundationBoundary`r`n")
        [void]$foundationMultipart.Append("Content-Disposition: form-data; name=`"$($field.Key)`"`r`n`r`n")
        [void]$foundationMultipart.Append("$($field.Value)`r`n")
    }
    [void]$foundationMultipart.Append("--$foundationBoundary--`r`n")
    $foundationMultipartBytes = [Text.Encoding]::UTF8.GetBytes($foundationMultipart.ToString())
    $webFoundationResponse = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/onboarding" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin } `
        -ContentType "multipart/form-data; boundary=$foundationBoundary" `
        -Body $foundationMultipartBytes -WebSession $ownerWebSession
    if (-not $webFoundationResponse.Content.Contains("Target audience") -or `
            -not $webFoundationResponse.Content.Contains("Market")) {
        throw "Real onboarding web action did not persist and resume at step two"
    }
    $webBrainPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/brain" -WebSession $ownerWebSession
    if (-not $webBrainPage.Content.Contains("Unified, provenance-first context") -or `
            -not $webBrainPage.Content.Contains("Model-ready context") -or `
            -not $webBrainPage.Content.Contains(
                "No founder-approved onboarding profile exists"
            )) {
        throw "Protected business brain and unavailable-source state did not render"
    }

    $settingsPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/settings/security" -WebSession $ownerWebSession
    if (-not $settingsPage.Content.Contains("Owner settings")) {
        throw "Authenticated security settings did not render"
    }
    $aiSettingsPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/settings/ai" -WebSession $ownerWebSession
    if (-not $aiSettingsPage.Content.Contains("Provider-independent AI routing") -or `
            -not $aiSettingsPage.Content.Contains("Run live gateway check")) {
        throw "Protected model gateway settings did not render"
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
    if ($LASTEXITCODE -ne 0 -or $smokeVersion.Trim() -ne "20260822_05") {
        throw "Isolated Phase 06 schema baseline is not current"
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
    $onboardingDraftCount = docker compose exec -T postgres psql -U foundora -d $smokeDatabase `
        -tAc "SELECT count(*) FROM business_onboarding_drafts"
    if ($LASTEXITCODE -ne 0 -or $onboardingDraftCount.Trim() -ne "2") {
        throw "Expected isolated Alpha and web onboarding drafts"
    }
    $approvedProfileEvidence = docker compose exec -T postgres psql -U foundora -d $smokeDatabase `
        -tAc "SELECT count(*) || '|' || min(version) || '|' || min(offer) FROM approved_business_profiles"
    if ($LASTEXITCODE -ne 0 -or `
            $approvedProfileEvidence.Trim() -ne "1|2|A revised founder-approved operating profile") {
        throw "Founder-approved profile evidence is incorrect"
    }
    $gatewayUsageEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT count(*) || '|' || count(*) FILTER (WHERE status = 'succeeded') || '|' || coalesce(sum(total_tokens), 0) FROM model_gateway_calls WHERE business_id = '$businessBId'"
    $gatewayUsageParts = $gatewayUsageEvidence.Trim().Split("|")
    if ($LASTEXITCODE -ne 0 -or $gatewayUsageParts.Count -ne 3 -or `
            [int]$gatewayUsageParts[0] -lt 1 -or [int]$gatewayUsageParts[1] -ne 1 -or `
            [int]$gatewayUsageParts[2] -le 0) {
        throw "Persisted model usage evidence is incorrect"
    }
    $providerValidationCount = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc "SELECT count(*) FROM model_provider_validations"
    if ($LASTEXITCODE -ne 0 -or $providerValidationCount.Trim() -ne "3") {
        throw "Expected all provider validation outcomes to be persisted"
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
    $foundationForm = $null
    $foundationMultipart = $null
    $foundationMultipartBytes = $null
    $liveGatewayBody = $null
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
if ($LASTEXITCODE -ne 0 -or $migrationVersion.Trim() -ne "20260822_05") {
    throw "Phase 06 schema baseline is not current"
}
Invoke-Checked { docker compose exec -T worker python -m foundora.worker_health }

Invoke-Checked { docker compose ps }
