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

function Wait-ForAgentRun {
    param(
        [string]$Uri,
        [object]$WebSession,
        [int]$Attempts = 60
    )
    foreach ($attempt in 1..$Attempts) {
        $run = Invoke-RestMethod -Uri $Uri -WebSession $WebSession
        if ($run.status -in @("completed", "failed", "cancelled")) { return $run }
        Start-Sleep -Seconds 1
    }
    throw "Agent run did not reach a terminal state: $Uri"
}

function Wait-ForWorkflowState {
    param(
        [string]$Uri,
        [object]$WebSession,
        [string[]]$ExpectedStates,
        [int]$Attempts = 30
    )
    foreach ($attempt in 1..$Attempts) {
        $run = Invoke-RestMethod -Uri $Uri -WebSession $WebSession
        if ($run.status -in $ExpectedStates) { return $run }
        if ($run.status -in @("failed", "cancelled")) {
            throw "Workflow reached unexpected terminal state $($run.status): $Uri"
        }
        Start-Sleep -Seconds 1
    }
    throw "Workflow did not reach $($ExpectedStates -join ', '): $Uri"
}

function Invoke-WithTransientHttpRetry {
    param(
        [scriptblock]$Request,
        [int]$Attempts = 3
    )
    foreach ($attempt in 1..$Attempts) {
        try {
            return & $Request
        }
        catch {
            $response = $_.Exception.Response
            if (-not $response) { throw }
            $statusCode = [int]$response.StatusCode
            if ($statusCode -notin @(502, 503, 504) -or $attempt -eq $Attempts) {
                throw
            }
        }
        Start-Sleep -Seconds (20 * $attempt)
    }
    throw "Transient HTTP request exhausted its bounded retries"
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
$smokeWorkerContainer = "foundora-worker-smoke-$runId"
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
            -e FOUNDORA_KNOWLEDGE_STORAGE_PATH=/tmp/foundora-knowledge-$runId `
            -e FOUNDORA_PUBLIC_ORIGIN=$smokePublicOrigin api
    }
    Invoke-Checked {
        docker compose run --detach --no-deps --name $smokeWebContainer `
            --publish "127.0.0.1:${authWebPort}:3000" `
            -e API_INTERNAL_URL=http://${smokeApiContainer}:8000 `
            -e FOUNDORA_PUBLIC_ORIGIN=$smokePublicOrigin web
    }
    Invoke-Checked {
        docker compose run --detach --no-deps --name $smokeWorkerContainer `
            -e FOUNDORA_DATABASE_URL=$smokeDatabaseUrl `
            -e FOUNDORA_REDIS_URL=redis://redis:6379/1 `
            -e FOUNDORA_KNOWLEDGE_STORAGE_PATH=/tmp/foundora-knowledge-$runId worker
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
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/agents"
    }
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/workflows"
    }
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/governance"
    }
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/events"
    }
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/knowledge"
    }
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/knowledge/search?q=evidence"
    }
    Assert-HttpStatus -ExpectedStatus 401 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/memory"
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

    $blockerTask = Invoke-RestMethod -Uri "$smokeApiOrigin/tasks" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            title = "Approve launch brief"
            description = "Durable dependency for Phase 09 acceptance"
            goal_id = $goalBId
            priority = 1
            owner_type = "founder"
            owner_agent_id = $null
            due_at = "2026-12-01T09:00:00Z"
            max_retries = 0
        } | ConvertTo-Json -Compress)
    $blockerTaskId = [string]$blockerTask.id
    $dependentTask = Invoke-RestMethod -Uri "$smokeApiOrigin/tasks" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            title = "Publish launch brief"
            description = "Must wait for approval task"
            goal_id = $goalBId
            priority = 2
            owner_type = "agent"
            owner_agent_id = "runtime-verification-agent"
            due_at = $null
            max_retries = 2
        } | ConvertTo-Json -Compress)
    $dependentTaskId = [string]$dependentTask.id
    $dependentTask = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/tasks/$dependentTaskId/dependencies" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ depends_on_task_id = $blockerTaskId } | ConvertTo-Json -Compress)
    if ($dependentTask.dependencies.Count -ne 1 -or `
            $dependentTask.blocked_by.Count -ne 1 -or `
            -not $dependentTask.owner_agent_version_id) {
        throw "Task dependency or pinned agent owner was not persisted"
    }
    Assert-HttpStatus -ExpectedStatus 409 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/tasks/$blockerTaskId/dependencies" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ depends_on_task_id = $dependentTaskId } | ConvertTo-Json -Compress)
    }
    Invoke-RestMethod -Uri "$smokeApiOrigin/tasks/$dependentTaskId/status" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ status = "planned" } | ConvertTo-Json -Compress) | Out-Null
    Assert-HttpStatus -ExpectedStatus 409 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/tasks/$dependentTaskId/status" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ status = "queued" } | ConvertTo-Json -Compress)
    }
    foreach ($nextState in @("planned", "queued", "running", "completed")) {
        $blockerTask = Invoke-RestMethod `
            -Uri "$smokeApiOrigin/tasks/$blockerTaskId/status" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ status = $nextState } | ConvertTo-Json -Compress)
    }
    foreach ($nextState in @("queued", "running", "failed")) {
        $transitionBody = @{ status = $nextState }
        if ($nextState -eq "failed") { $transitionBody.error = "Deterministic smoke failure" }
        $dependentTask = Invoke-RestMethod `
            -Uri "$smokeApiOrigin/tasks/$dependentTaskId/status" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body ($transitionBody | ConvertTo-Json -Compress)
    }
    $taskRetryKey = "smoke:${runId}:dependent-retry"
    $taskRetryBody = @{ idempotency_key = $taskRetryKey } | ConvertTo-Json -Compress
    $retriedTask = Invoke-RestMethod -Uri "$smokeApiOrigin/tasks/$dependentTaskId/retry" `
        -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession -Body $taskRetryBody
    $duplicateRetry = Invoke-RestMethod -Uri "$smokeApiOrigin/tasks/$dependentTaskId/retry" `
        -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession -Body $taskRetryBody
    if ($retriedTask.status -ne "queued" -or $retriedTask.retry_count -ne 1 -or `
            $duplicateRetry.retry_count -ne 1 -or `
            @($duplicateRetry.events | Where-Object { $_.event_type -eq "retried" }).Count -ne 1) {
        throw "Task retry was not atomic and idempotent"
    }

    $workflowRun = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/workflows/durable-checkpoint-workflow/runs" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            input = @{ message = "Phase 10 durable smoke"; include_branch = $true }
            task_id = $dependentTaskId
        } | ConvertTo-Json -Depth 4 -Compress)
    $workflowRunId = [string]$workflowRun.id
    $workflowRunUri = "$smokeApiOrigin/workflows/runs/$workflowRunId"
    $workflowRun = Wait-ForWorkflowState -Uri $workflowRunUri `
        -WebSession $ownerSession -ExpectedStates @("waiting_approval")
    if ($workflowRun.current_step_key -ne "owner_checkpoint" -or `
            @($workflowRun.steps | Where-Object { $_.status -eq "completed" }).Count -ne 2) {
        throw "Workflow did not execute its dependency and conditional branch before approval"
    }
    $approvalResumeKey = "smoke:${runId}:workflow-approval"
    $approvalResumeBody = @{
        idempotency_key = $approvalResumeKey
        decision = "approved"
        input = @{}
    } | ConvertTo-Json -Depth 3 -Compress
    Invoke-RestMethod -Uri "$workflowRunUri/resume" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body $approvalResumeBody | Out-Null
    Invoke-RestMethod -Uri "$workflowRunUri/resume" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body $approvalResumeBody | Out-Null
    $workflowRun = Wait-ForWorkflowState -Uri $workflowRunUri `
        -WebSession $ownerSession -ExpectedStates @("waiting")
    if ($workflowRun.current_step_key -ne "durable_wait") {
        throw "Workflow did not resume from approval into its durable wait"
    }
    $waitResumeKey = "smoke:${runId}:workflow-wait"
    $waitResumeBody = @{
        idempotency_key = $waitResumeKey
        decision = $null
        input = @{ evidence = "resumed" }
    } | ConvertTo-Json -Depth 3 -Compress
    Invoke-RestMethod -Uri "$workflowRunUri/resume" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body $waitResumeBody | Out-Null
    $workflowRun = Wait-ForWorkflowState -Uri $workflowRunUri `
        -WebSession $ownerSession -ExpectedStates @("completed")
    if ($workflowRun.output.steps.finish.result -ne "workflow_complete" -or `
            @($workflowRun.events | Where-Object { $_.event_type -eq "owner_resumed" }).Count -ne 2) {
        throw "Workflow did not complete deterministically with idempotent resume evidence"
    }
    $rejectedWorkflow = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/workflows/durable-checkpoint-workflow/runs" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            input = @{ message = "Phase 10 rejection smoke"; include_branch = $false }
            task_id = $null
        } | ConvertTo-Json -Depth 4 -Compress)
    $rejectedWorkflowId = [string]$rejectedWorkflow.id
    $rejectedWorkflowUri = "$smokeApiOrigin/workflows/runs/$rejectedWorkflowId"
    $rejectedWorkflow = Wait-ForWorkflowState -Uri $rejectedWorkflowUri `
        -WebSession $ownerSession -ExpectedStates @("waiting_approval")
    if (@($rejectedWorkflow.steps | Where-Object {
                $_.key -eq "optional_branch" -and $_.status -eq "skipped"
            }).Count -ne 1) {
        throw "Workflow false conditional branch was not skipped deterministically"
    }
    $rejectionBody = @{
        idempotency_key = "smoke:${runId}:workflow-rejection"
        decision = "rejected"
        input = @{}
    } | ConvertTo-Json -Depth 3 -Compress
    $rejectedWorkflow = Invoke-RestMethod -Uri "$rejectedWorkflowUri/resume" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body $rejectionBody
    if ($rejectedWorkflow.status -ne "failed" -or `
            $rejectedWorkflow.error_type -ne "checkpoint_rejected" -or `
            @($rejectedWorkflow.steps | Where-Object {
                $_.key -eq "capture" -and $_.status -eq "compensated"
            }).Count -ne 1 -or `
            @($rejectedWorkflow.events | Where-Object {
                $_.event_type -eq "step_compensated"
            }).Count -ne 1) {
        throw "Workflow rejection failure or reverse compensation was not deterministic"
    }

    $governanceDashboard = Invoke-RestMethod -Uri "$smokeApiOrigin/governance" `
        -WebSession $ownerSession
    if ($governanceDashboard.policy.policy_id -ne "foundora-default-governance" -or `
            $governanceDashboard.policy.version -ne 1 -or `
            $governanceDashboard.settings.autonomy_level -ne "OFF" -or `
            $governanceDashboard.settings.daily_spend_limit_microusd -ne 0 -or `
            $governanceDashboard.controls.kill_switch_enabled -or `
            $governanceDashboard.tool_permissions.Count -ne 3) {
        throw "Default Phase 11 policy and least-authority controls are incorrect"
    }

    $rejectedR3 = Invoke-RestMethod -Uri "$smokeApiOrigin/governance/actions/evaluate" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            action_type = "external.publication"
            execution_mode = "manual"
            data_classification = "internal"
            requested_spend_microusd = 0
            frequency_key = "smoke-publication"
            target = "provider-neutral-publication-target"
            idempotency_key = "smoke:${runId}:r3-rejected"
        } | ConvertTo-Json -Compress)
    if ($rejectedR3.risk_class -ne "R3" -or `
            $rejectedR3.status -ne "approval_required" -or `
            $rejectedR3.approval.status -ne "pending") {
        throw "R3 action did not require a durable owner approval"
    }
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/governance/actions/$($rejectedR3.id)/authorize" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                idempotency_key = "smoke:${runId}:r3-bypass"
            } | ConvertTo-Json -Compress)
    }
    $rejectedR3 = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/governance/approvals/$($rejectedR3.approval.id)/decide" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            decision = "rejected"
            reason = "Phase 11 deterministic rejection"
            idempotency_key = "smoke:${runId}:r3-reject-decision"
        } | ConvertTo-Json -Compress)
    if ($rejectedR3.status -ne "rejected" -or $rejectedR3.approval.status -ne "rejected") {
        throw "Rejected R3 approval did not become terminal"
    }
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/governance/actions/$($rejectedR3.id)/authorize" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                idempotency_key = "smoke:${runId}:r3-after-rejection"
            } | ConvertTo-Json -Compress)
    }

    $zeroBudgetR4 = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/governance/actions/evaluate" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            action_type = "financial.spend"
            execution_mode = "manual"
            data_classification = "internal"
            requested_spend_microusd = 1
            target = "provider-neutral-budget-target"
            idempotency_key = "smoke:${runId}:r4-zero-budget"
        } | ConvertTo-Json -Compress)
    if ($zeroBudgetR4.risk_class -ne "R4" -or $zeroBudgetR4.status -ne "denied") {
        throw "Zero-by-default spend policy did not deny R4 spend"
    }

    $governanceSettings = Invoke-RestMethod -Uri "$smokeApiOrigin/governance/settings" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            autonomy_level = "AUTONOMOUS_LOW_RISK"
            daily_spend_limit_microusd = 10000
            per_action_spend_limit_microusd = 5000
            revision = $governanceDashboard.settings.revision
        } | ConvertTo-Json -Compress)
    if ($governanceSettings.autonomy_level -ne "AUTONOMOUS_LOW_RISK" -or `
            $governanceSettings.revision -ne 2) {
        throw "Selected-business autonomy and spend controls did not persist"
    }

    $approvedR4 = Invoke-RestMethod -Uri "$smokeApiOrigin/governance/actions/evaluate" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            action_type = "financial.spend"
            execution_mode = "manual"
            data_classification = "internal"
            requested_spend_microusd = 1000
            target = "provider-neutral-approved-budget"
            idempotency_key = "smoke:${runId}:r4-approved"
        } | ConvertTo-Json -Compress)
    if ($approvedR4.risk_class -ne "R4" -or $approvedR4.status -ne "approval_required") {
        throw "Within-limit R4 spend bypassed explicit approval"
    }
    $approvedR4 = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/governance/approvals/$($approvedR4.approval.id)/decide" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            decision = "approved"
            reason = "Phase 11 explicit R4 approval"
            idempotency_key = "smoke:${runId}:r4-approve-decision"
        } | ConvertTo-Json -Compress)
    $approvedR4 = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/governance/actions/$($approvedR4.id)/authorize" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            idempotency_key = "smoke:${runId}:r4-authorize"
        } | ConvertTo-Json -Compress)
    if ($approvedR4.status -ne "authorized" -or `
            $approvedR4.requested_spend_microusd -ne 1000) {
        throw "Approved R4 action did not pass the execution-time spend recheck"
    }

    $approvedR3 = Invoke-RestMethod -Uri "$smokeApiOrigin/governance/actions/evaluate" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            action_type = "external.communication"
            execution_mode = "manual"
            data_classification = "confidential"
            requested_spend_microusd = 0
            target = "provider-neutral-recipient"
            idempotency_key = "smoke:${runId}:r3-approved"
        } | ConvertTo-Json -Compress)
    $approvedR3 = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/governance/approvals/$($approvedR3.approval.id)/decide" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            decision = "approved"
            reason = "Phase 11 explicit R3 approval"
            idempotency_key = "smoke:${runId}:r3-approve-decision"
        } | ConvertTo-Json -Compress)
    $approvedR3 = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/governance/actions/$($approvedR3.id)/authorize" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            idempotency_key = "smoke:${runId}:r3-authorize"
        } | ConvertTo-Json -Compress)
    if ($approvedR3.status -ne "authorized") {
        throw "Approved R3 action did not pass execution-time policy recheck"
    }

    $autonomousR0 = Invoke-RestMethod -Uri "$smokeApiOrigin/governance/actions/evaluate" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            action_type = "internal.analysis"
            execution_mode = "autonomous"
            data_classification = "internal"
            requested_spend_microusd = 0
            idempotency_key = "smoke:${runId}:autonomous-r0"
        } | ConvertTo-Json -Compress)
    if ($autonomousR0.status -ne "authorized" -or $autonomousR0.risk_class -ne "R0") {
        throw "AUTONOMOUS_LOW_RISK did not permit the low-risk smoke authorization"
    }

    $echoPermission = $governanceDashboard.tool_permissions | `
        Where-Object { $_.tool_id -eq "foundora.internal.echo" } | Select-Object -First 1
    $echoPermission = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/governance/tools/foundora.internal.echo/permission" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            enabled = $false
            revision = $echoPermission.revision
        } | ConvertTo-Json -Compress)
    $disabledToolWorkflow = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/workflows/durable-checkpoint-workflow/runs" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            input = @{ message = "Phase 11 disabled tool"; include_branch = $false }
            task_id = $null
        } | ConvertTo-Json -Depth 4 -Compress)
    $disabledToolWorkflowId = [string]$disabledToolWorkflow.id
    $disabledToolWorkflow = Wait-ForWorkflowState `
        -Uri "$smokeApiOrigin/workflows/runs/$disabledToolWorkflowId" `
        -WebSession $ownerSession -ExpectedStates @("failed")
    if ($disabledToolWorkflow.error_type -ne "governance_denied") {
        throw "Disabled tool permission did not block workflow execution"
    }
    $echoPermission = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/governance/tools/foundora.internal.echo/permission" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            enabled = $true
            revision = $echoPermission.revision
        } | ConvertTo-Json -Compress)

    $killSwitch = Invoke-RestMethod -Uri "$smokeApiOrigin/governance/kill-switch" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            enabled = $true
            reason = "Phase 11 workflow enforcement smoke"
            revision = $governanceDashboard.controls.revision
        } | ConvertTo-Json -Compress)
    $killedWorkflow = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/workflows/durable-checkpoint-workflow/runs" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            input = @{ message = "Phase 11 kill switch"; include_branch = $false }
            task_id = $null
        } | ConvertTo-Json -Depth 4 -Compress)
    $killedWorkflowId = [string]$killedWorkflow.id
    $killedWorkflow = Wait-ForWorkflowState `
        -Uri "$smokeApiOrigin/workflows/runs/$killedWorkflowId" `
        -WebSession $ownerSession -ExpectedStates @("failed")
    if ($killedWorkflow.error_type -ne "governance_denied") {
        throw "Global kill switch did not block workflow execution beneath prompts"
    }
    $killSwitch = Invoke-RestMethod -Uri "$smokeApiOrigin/governance/kill-switch" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            enabled = $false
            reason = $null
            revision = $killSwitch.revision
        } | ConvertTo-Json -Compress)
    if ($killSwitch.kill_switch_enabled) {
        throw "Global kill switch did not release after the enforcement smoke"
    }

    $knowledgeSource = Invoke-RestMethod -Uri "$smokeApiOrigin/knowledge/sources" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            title = "Beta founder research"
            source_type = "upload"
            source_uri = "https://example.com/beta-research"
            metadata = @{ author = "Founder"; classification = "internal" }
        } | ConvertTo-Json -Depth 4 -Compress)
    $knowledgeSourceId = [string]$knowledgeSource.id
    $knowledgeText = @"
# Beta retention evidence

Quasar retention research shows founder-led design studios prefer predictable annual subscriptions and transparent onboarding.
"@
    $knowledgeBytes = [Text.Encoding]::UTF8.GetBytes($knowledgeText)
    $knowledgeUploadUri = "$smokeApiOrigin/knowledge/sources/$knowledgeSourceId/documents?filename=beta-evidence.md&file_media_type=text%2Fmarkdown"
    $knowledgeDocument = Invoke-RestMethod -Uri $knowledgeUploadUri -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/octet-stream" -WebSession $ownerSession `
        -Body $knowledgeBytes
    $knowledgeDocumentId = [string]$knowledgeDocument.id
    if ($knowledgeDocument.status -ne "indexed" -or `
            $knowledgeDocument.chunk_count -lt 1 -or `
            $knowledgeDocument.embedding_model -ne "foundora.local-feature-hash.v1") {
        throw "Uploaded Phase 13 document was not extracted, embedded, and indexed"
    }
    Assert-HttpStatus -ExpectedStatus 422 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri $knowledgeUploadUri -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/octet-stream" -WebSession $ownerSession `
            -Body $knowledgeBytes
    }
    Assert-HttpStatus -ExpectedStatus 422 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/knowledge/sources/$knowledgeSourceId/documents?filename=malformed.json&file_media_type=application%2Fjson" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/octet-stream" -WebSession $ownerSession `
            -Body ([Text.Encoding]::UTF8.GetBytes('{"broken":'))
    }
    $knowledgeSearch = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/knowledge/search?q=quasar%20retention%20studios" `
        -WebSession $ownerSession
    $retrievedKnowledge = @($knowledgeSearch.hits | Where-Object {
            $_.citation.document_id -eq $knowledgeDocumentId
        }) | Select-Object -First 1
    if (-not $retrievedKnowledge -or `
            $retrievedKnowledge.citation.source_id -ne $knowledgeSourceId -or `
            $retrievedKnowledge.citation.source_uri -ne "https://example.com/beta-research" -or `
            -not ([string]$retrievedKnowledge.text).Contains("predictable annual subscriptions")) {
        throw "Uploaded Phase 13 document was not retrievable with its source citation"
    }
    $knowledgeBrain = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/brain/context?purpose=planning&token_budget=4096&sources=knowledge&knowledge_query=quasar%20retention%20studios" `
        -WebSession $ownerSession
    if ($knowledgeBrain.business_id -ne $businessBId -or `
            -not ([string]$knowledgeBrain.context).Contains("predictable annual subscriptions") -or `
            -not ([string]$knowledgeBrain.context).Contains($knowledgeDocumentId)) {
        throw "Cited Phase 13 retrieval did not enter selected-business context"
    }

    $invalidatedSource = Invoke-RestMethod -Uri "$smokeApiOrigin/knowledge/sources" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            title = "Invalidation probe"
            source_type = "upload"
            source_uri = $null
            metadata = @{}
        } | ConvertTo-Json -Depth 3 -Compress)
    $invalidatedSourceId = [string]$invalidatedSource.id
    $invalidatedBytes = [Text.Encoding]::UTF8.GetBytes(
        "Obsoleteorionmarker evidence must disappear from active retrieval."
    )
    $invalidatedDocument = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/knowledge/sources/$invalidatedSourceId/documents?filename=obsolete.txt&file_media_type=text%2Fplain" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/octet-stream" -WebSession $ownerSession `
        -Body $invalidatedBytes
    $invalidatedDocumentId = [string]$invalidatedDocument.id
    Invoke-RestMethod `
        -Uri "$smokeApiOrigin/knowledge/documents/$invalidatedDocumentId/invalidate" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ expected_revision = 1; reason = "Superseded evidence" } | ConvertTo-Json -Compress) | Out-Null
    Invoke-RestMethod `
        -Uri "$smokeApiOrigin/knowledge/sources/$invalidatedSourceId/invalidate" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ expected_revision = 1; reason = "Source retired" } | ConvertTo-Json -Compress) | Out-Null
    $invalidatedSearch = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/knowledge/search?q=obsoleteorionmarker" `
        -WebSession $ownerSession
    if (@($invalidatedSearch.hits | Where-Object {
                $_.citation.document_id -eq $invalidatedDocumentId
            }).Count -ne 0) {
        throw "Invalidated Phase 13 knowledge remained retrievable"
    }

    $memoryProposalBody = @{
        memory_type = "semantic"
        epistemic_status = "assumption"
        title = "Quasar retention hypothesis"
        content = "Quasar studios may retain better with predictable annual subscriptions."
        confidence = 0.78
        execution_type = $null
        execution_id = $null
        expires_at = $null
        source_kind = "knowledge_chunk"
        source_id = [string]$retrievedKnowledge.citation.chunk_id
        source_uri = $null
        source_label = "Ignored client label"
        source_excerpt = $null
        source_metadata = @{}
    }
    $memoryProposal = Invoke-RestMethod -Uri "$smokeApiOrigin/memory/proposals" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body ($memoryProposalBody | ConvertTo-Json -Depth 5 -Compress)
    if ($memoryProposal.status -ne "pending" -or `
            $memoryProposal.acceptance_route -ne "founder" -or `
            $memoryProposal.epistemic_status -ne "assumption" -or `
            -not ([string]$memoryProposal.source_label).Contains("Beta founder research") -or `
            -not ([string]$memoryProposal.source_label).Contains("beta-evidence.md")) {
        throw "Curator proposal did not preserve its assumption label or verified provenance"
    }
    $acceptedMemoryProposal = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/memory/proposals/$($memoryProposal.id)/accept" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            expected_revision = $memoryProposal.revision
            reason = "Founder accepts this as a labeled hypothesis"
        } | ConvertTo-Json -Compress)
    $memoryId = [string]$acceptedMemoryProposal.resolution_memory_id
    if ($acceptedMemoryProposal.status -ne "accepted" -or -not $memoryId) {
        throw "Founder acceptance did not create durable memory"
    }
    $memoryBrain = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/brain/context?purpose=planning&token_budget=4096&sources=relevant_memories&memory_query=quasar" `
        -WebSession $ownerSession
    if (-not ([string]$memoryBrain.context).Contains($memoryId) -or `
            -not ([string]$memoryBrain.context).Contains('"epistemic_status":"assumption"') -or `
            -not ([string]$memoryBrain.context).Contains('"authority":"curated_assumption"')) {
        throw "Labeled Phase 14 memory did not enter Business Brain with visible authority"
    }

    $duplicateMemoryProposal = Invoke-RestMethod -Uri "$smokeApiOrigin/memory/proposals" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            memory_type = "semantic"
            epistemic_status = "assumption"
            title = "  quasar   retention HYPOTHESIS "
            content = "quasar studios may retain better with predictable annual subscriptions."
            confidence = 0.81
            execution_type = $null
            execution_id = $null
            expires_at = $null
            source_kind = "founder_input"
            source_id = $null
            source_uri = "https://example.com/founder-review"
            source_label = "Founder duplicate review"
            source_excerpt = "Same hypothesis confirmed in founder review."
            source_metadata = @{ review = "duplicate-check" }
        } | ConvertTo-Json -Depth 5 -Compress)
    $mergedMemoryProposal = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/memory/proposals/$($duplicateMemoryProposal.id)/accept" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            expected_revision = $duplicateMemoryProposal.revision
            reason = "Merge exact duplicate provenance"
        } | ConvertTo-Json -Compress)
    if ($mergedMemoryProposal.status -ne "merged" -or `
            $mergedMemoryProposal.resolution_memory_id -ne $memoryId) {
        throw "Exact duplicate memory did not merge into the existing record"
    }

    $factProposal = Invoke-RestMethod -Uri "$smokeApiOrigin/memory/proposals" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            memory_type = "semantic"
            epistemic_status = "fact"
            title = "Approved subscription model"
            content = "Annual subscriptions are the founder-approved commercial model."
            confidence = 1.0
            execution_type = $null
            execution_id = $null
            expires_at = $null
            source_kind = "founder_input"
            source_id = $null
            source_uri = "https://example.com/founder-decision"
            source_label = "Founder commercial review"
            source_excerpt = "Founder explicitly approved the commercial model."
            source_metadata = @{}
        } | ConvertTo-Json -Depth 4 -Compress)
    if ($factProposal.status -ne "pending" -or $factProposal.acceptance_route -ne "founder") {
        throw "A semantic fact bypassed explicit founder acceptance"
    }
    $acceptedFact = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/memory/proposals/$($factProposal.id)/accept" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            expected_revision = $factProposal.revision
            reason = "Founder confirms this as an approved fact"
        } | ConvertTo-Json -Compress)
    $factMemoryId = [string]$acceptedFact.resolution_memory_id
    Assert-HttpStatus -ExpectedStatus 422 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/memory/proposals" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                memory_type = "semantic"; epistemic_status = "assumption"
                title = "Credential probe"; content = "api_key=sk-abcdefghijklmnopqrstuvwxyz"
                confidence = 0.9; execution_type = $null; execution_id = $null
                expires_at = $null; source_kind = "founder_input"; source_id = $null
                source_uri = $null; source_label = "Security probe"; source_excerpt = $null
                source_metadata = @{}
            } | ConvertTo-Json -Depth 4 -Compress)
    }

    $memoryPolicy = Invoke-RestMethod -Uri "$smokeApiOrigin/memory/policy" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            automatic_accept_types = @("episodic")
            minimum_confidence = 0.9
            expected_revision = 0
        } | ConvertTo-Json -Compress)
    $automaticMemory = Invoke-RestMethod -Uri "$smokeApiOrigin/memory/proposals" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{
            memory_type = "episodic"; epistemic_status = "observation"
            title = "Task retry outcome"; content = "The dependency-gated task completed after one bounded retry."
            confidence = 0.95; execution_type = $null; execution_id = $null; expires_at = $null
            source_kind = "task"; source_id = $dependentTaskId; source_uri = $null
            source_label = "Ignored task label"; source_excerpt = $null; source_metadata = @{}
        } | ConvertTo-Json -Depth 4 -Compress)
    if ($automaticMemory.status -ne "accepted" -or `
            $automaticMemory.acceptance_route -ne "automatic" -or `
            -not $automaticMemory.resolution_memory_id) {
        throw "Configured safe automatic memory acceptance did not run"
    }

    Invoke-RestMethod -Uri "$smokeApiOrigin/memory/records/$memoryId/invalidate" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ expected_revision = 2; reason = "Hypothesis superseded" } | ConvertTo-Json -Compress) | Out-Null
    $invalidatedMemoryBrain = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/brain/context?purpose=planning&token_budget=4096&sources=relevant_memories&memory_query=quasar" `
        -WebSession $ownerSession
    if (([string]$invalidatedMemoryBrain.context).Contains($memoryId)) {
        throw "Invalidated Phase 14 memory remained retrievable"
    }

    Invoke-Checked {
        docker exec $smokeApiContainer python -m foundora.events.dispatcher --limit 1000
    }
    $eventDashboard = Invoke-RestMethod -Uri "$smokeApiOrigin/events" `
        -WebSession $ownerSession
    $eventTypes = @($eventDashboard.events | ForEach-Object { $_.event_type })
    foreach ($requiredEventType in @(
            "business.created",
            "goal.created",
            "task.completed",
            "task.failed",
            "approval.requested",
            "knowledge.source_registered",
            "knowledge.document_indexed",
            "knowledge.document_invalidated",
            "knowledge.source_invalidated",
            "memory.proposed",
            "memory.accepted",
            "memory.merged",
            "memory.invalidated"
        )) {
        if ($requiredEventType -notin $eventTypes) {
            throw "Required Phase 12-14 event was not published: $requiredEventType"
        }
    }
    $eventDeliveries = @($eventDashboard.events | ForEach-Object { $_.deliveries })
    if ($eventDashboard.business_id -ne $businessBId -or `
            $eventDashboard.contracts.Count -ne 16 -or `
            @($eventDeliveries | Where-Object {
                $_.status -ne "completed" -or $_.attempt_count -ne 1
            }).Count -ne 0) {
        throw "Registered Phase 12-14 handlers did not complete exactly as designed"
    }
    $deliveryAttemptsBefore = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT coalesce(sum(d.attempt_count), 0) FROM event_deliveries d JOIN domain_events e ON e.id = d.event_id WHERE e.business_id = '$businessBId'"
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect Phase 12 delivery attempts" }
    Invoke-Checked {
        docker exec $smokeApiContainer python -m foundora.events.dispatcher --limit 1000
    }
    $deliveryAttemptsAfter = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT coalesce(sum(d.attempt_count), 0) FROM event_deliveries d JOIN domain_events e ON e.id = d.event_id WHERE e.business_id = '$businessBId'"
    if ($LASTEXITCODE -ne 0 -or `
            $deliveryAttemptsAfter.Trim() -ne $deliveryAttemptsBefore.Trim()) {
        throw "Completed Phase 12 handlers were invoked more than once"
    }

    $deadLetterDeliveryId = [guid]::NewGuid().ToString()
    $eventProbeId = [string]$eventDashboard.events[0].id
    docker compose exec -T postgres psql -U foundora -d $smokeDatabase -v ON_ERROR_STOP=1 `
        -c "INSERT INTO event_deliveries (id, event_id, consumer_name, status, attempt_count, max_attempts, redrive_count, available_at, created_at, updated_at) VALUES ('$deadLetterDeliveryId', '$eventProbeId', 'foundora.missing-consumer.v1', 'pending', 0, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)" `
        | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare Phase 12 dead-letter probe" }
    Invoke-Checked {
        docker exec $smokeApiContainer python -m foundora.events.dispatcher --limit 10
    }
    $deadLetters = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/events?delivery_status=dead_letter" `
        -WebSession $ownerSession
    $deadLetter = @($deadLetters.events | ForEach-Object { $_.deliveries } | `
        Where-Object { $_.id -eq $deadLetterDeliveryId }) | Select-Object -First 1
    if (-not $deadLetter -or $deadLetter.status -ne "dead_letter" -or `
            $deadLetter.attempt_count -ne 1 -or `
            $deadLetter.last_error_type -ne "EventContractErrorForDelivery" -or `
            $deadLetter.last_error_message -ne "The registered event handler failed") {
        throw "Failed Phase 12 delivery did not enter the sanitized dead-letter state"
    }
    Invoke-RestMethod `
        -Uri "$smokeApiOrigin/events/deliveries/$deadLetterDeliveryId/redrive" `
        -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ expected_redrive_count = 0 } | ConvertTo-Json -Compress) | Out-Null
    Invoke-Checked {
        docker exec $smokeApiContainer python -m foundora.events.dispatcher --limit 10
    }
    Assert-HttpStatus -ExpectedStatus 409 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/events/deliveries/$deadLetterDeliveryId/redrive" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ expected_redrive_count = 0 } | ConvertTo-Json -Compress)
    }

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
    $alphaGovernance = Invoke-RestMethod -Uri "$smokeApiOrigin/governance" `
        -WebSession $ownerSession
    if ($alphaGovernance.business_id -ne $businessAId -or `
            $alphaGovernance.actions.Count -ne 0 -or `
            $alphaGovernance.settings.autonomy_level -ne "OFF") {
        throw "Governance actions or selected-business controls crossed a business boundary"
    }
    $alphaKnowledge = Invoke-RestMethod -Uri "$smokeApiOrigin/knowledge" `
        -WebSession $ownerSession
    $alphaKnowledgeSearch = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/knowledge/search?q=quasar%20retention%20studios" `
        -WebSession $ownerSession
    if ($alphaKnowledge.business_id -ne $businessAId -or `
            @($alphaKnowledge.sources | Where-Object { $_.id -eq $knowledgeSourceId }).Count -ne 0 -or `
            @($alphaKnowledgeSearch.hits | Where-Object {
                    $_.citation.document_id -eq $knowledgeDocumentId
                }).Count -ne 0) {
        throw "Knowledge sources or retrieval crossed the selected-business boundary"
    }
    Assert-HttpStatus -ExpectedStatus 404 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/knowledge/sources/$knowledgeSourceId/invalidate" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ expected_revision = 1; reason = "Cross-business probe" } | ConvertTo-Json -Compress)
    }
    $alphaMemory = Invoke-RestMethod -Uri "$smokeApiOrigin/memory" `
        -WebSession $ownerSession
    if ($alphaMemory.business_id -ne $businessAId -or `
            @($alphaMemory.memories | Where-Object {
                    $_.id -in @($memoryId, $factMemoryId, [string]$automaticMemory.resolution_memory_id)
                }).Count -ne 0) {
        throw "Durable memory crossed the selected-business boundary"
    }
    Assert-HttpStatus -ExpectedStatus 404 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/memory/records/$factMemoryId/invalidate" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ expected_revision = 1; reason = "Cross-business probe" } | ConvertTo-Json -Compress)
    }
    $alphaEvents = Invoke-RestMethod -Uri "$smokeApiOrigin/events" `
        -WebSession $ownerSession
    if ($alphaEvents.business_id -ne $businessAId -or `
            @($alphaEvents.events | Where-Object { $_.business_id -ne $businessAId }).Count -ne 0 -or `
            @($alphaEvents.events | Where-Object { $_.aggregate_id -eq $businessBId }).Count -ne 0) {
        throw "Domain events crossed the selected-business boundary"
    }
    Assert-HttpStatus -ExpectedStatus 404 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/events/deliveries/$deadLetterDeliveryId/redrive" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ expected_redrive_count = 1 } | ConvertTo-Json -Compress)
    }
    Assert-HttpStatus -ExpectedStatus 404 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/tasks/$dependentTaskId" `
            -WebSession $ownerSession
    }
    Assert-HttpStatus -ExpectedStatus 404 -Request {
        Invoke-WebRequest -UseBasicParsing -Uri "$smokeApiOrigin/workflows/runs/$workflowRunId" `
            -WebSession $ownerSession
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

    # Phase 15 is deterministic and must remain independently observable even
    # when a later legacy live-provider check is unavailable or quota-limited.
    $phase15Dashboard = Invoke-RestMethod -Uri "$smokeApiOrigin/agents" `
        -WebSession $ownerSession
    $phase15Ceo = $phase15Dashboard.definitions | Where-Object {
        $_.agent_id -eq "founder-ceo"
    } | Select-Object -First 1
    $phase15Planning = $phase15Dashboard.definitions | Where-Object {
        $_.agent_id -eq "chief-of-staff-planning"
    } | Select-Object -First 1
    foreach ($executiveAgent in @($phase15Ceo, $phase15Planning)) {
        if (-not $executiveAgent -or `
                $executiveAgent.version -ne 1 -or `
                $executiveAgent.risk_level -ne "R0" -or `
                $executiveAgent.maximum_autonomy -ne "manual_advisory_only" -or `
                @($executiveAgent.allowed_tools).Count -ne 0 -or `
                @($executiveAgent.allowed_skills).Count -ne 0 -or `
                @($executiveAgent.assigned_skills).Count -ne 0 -or `
                @($executiveAgent.data_access_scope.sources) -notcontains "current_tasks" -or `
                @($executiveAgent.data_access_scope.sources) -notcontains "relevant_memories" -or `
                @($executiveAgent.forbidden_actions) -notcontains "Tool invocation") {
            throw "Phase 15 executive contract can exceed its advisory boundary"
        }
    }
    if (@($phase15Ceo.output_schema.required) -notcontains "priorities" -or `
            @($phase15Planning.output_schema.required) -notcontains "tasks" -or `
            @($phase15Planning.output_schema.required) -notcontains "progress_review") {
        throw "Phase 15 traceable priority, plan, or progress schemas are incomplete"
    }
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/agents/founder-ceo/runs" `
            -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = "" } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ objective = "Propose priorities" } | ConvertTo-Json -Compress)
    }
    $phase15LoginResponse = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokeApiOrigin/auth/login" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin } -ContentType "application/json" `
        -Body $loginBody -SessionVariable phase15WebSession
    if ($phase15LoginResponse.StatusCode -ne 200) {
        throw "Phase 15 UI inspection session could not authenticate"
    }
    $phase15CsrfCookie = $phase15WebSession.Cookies.GetCookies($smokeApiOrigin) | `
        Where-Object { $_.Name -eq "csrf" } | Select-Object -First 1
    Invoke-RestMethod -Uri "$smokeApiOrigin/businesses/select" -Method Post `
        -Headers @{
            Origin = $smokePublicOrigin
            "X-CSRF-Token" = $phase15CsrfCookie.Value
        } `
        -ContentType "application/json" -WebSession $phase15WebSession `
        -Body (@{ business_id = $businessBId } | ConvertTo-Json -Compress) | Out-Null
    $phase15AgentsPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/agents" -WebSession $phase15WebSession
    if (-not $phase15AgentsPage.Content.Contains("Founder / CEO Agent") -or `
            -not $phase15AgentsPage.Content.Contains("Chief-of-Staff / Planning Agent") -or `
            -not $phase15AgentsPage.Content.Contains("Queue manual R0 advisory run")) {
        throw "Phase 15 protected executive registry UI did not render"
    }
    Write-Output "Phase 15 executive contract smoke passed"

    # Phase 16 search is deterministic and performs no model-provider call.
    $phase16Dashboard = $phase15Dashboard
    $phase16AgentIds = @(
        "market-research",
        "competitor-intelligence",
        "customer-research"
    )
    foreach ($researchAgentId in $phase16AgentIds) {
        $researchAgent = $phase16Dashboard.definitions | Where-Object {
            $_.agent_id -eq $researchAgentId
        } | Select-Object -First 1
        if (-not $researchAgent -or `
                $researchAgent.version -ne 1 -or `
                $researchAgent.risk_level -ne "R0" -or `
                $researchAgent.maximum_autonomy -ne "manual_advisory_only" -or `
                @($researchAgent.allowed_tools).Count -ne 0 -or `
                @($researchAgent.allowed_skills).Count -ne 0 -or `
                @($researchAgent.assigned_skills).Count -ne 0 -or `
                $researchAgent.data_access_scope.research_evidence -ne `
                    "explicit_search_provider_results_only" -or `
                @($researchAgent.output_schema.required) -notcontains "findings" -or `
                @($researchAgent.output_schema.required) -notcontains `
                    "overall_limitations") {
            throw "Phase 16 research contract can exceed its source-backed advisory boundary"
        }
    }
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/agents/research/search" `
            -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = "" } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ query = "Quasar retention research" } | ConvertTo-Json -Compress)
    }
    $phase16Search = Invoke-RestMethod `
        -Uri "$smokeApiOrigin/agents/research/search" -Method Post `
        -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
        -ContentType "application/json" -WebSession $ownerSession `
        -Body (@{ query = "Quasar retention research" } | ConvertTo-Json -Compress)
    $phase16Evidence = $phase16Search.evidence | Where-Object {
        $_.source -eq "https://example.com/beta-research"
    } | Select-Object -First 1
    if ($phase16Search.provider -ne "registered_knowledge" -or `
            $phase16Search.query -ne "Quasar retention research" -or `
            -not $phase16Evidence -or `
            $phase16Evidence.source_title -ne "Beta founder research" -or `
            $phase16Evidence.retrieval_date -notmatch '^\d{4}-\d{2}-\d{2}$' -or `
            $phase16Evidence.evidence_id -notmatch `
                '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -or `
            $phase16Evidence.content_sha256 -notmatch '^[0-9a-f]{64}$' -or `
            -not ([string]$phase16Evidence.excerpt).Contains("Quasar retention research")) {
        throw "Phase 16 SearchProvider did not return exact durable source evidence"
    }
    if (-not $phase15AgentsPage.Content.Contains("Market Research Agent") -or `
            -not $phase15AgentsPage.Content.Contains("Competitor Intelligence Agent") -or `
            -not $phase15AgentsPage.Content.Contains("Customer Research Agent") -or `
            -not $phase15AgentsPage.Content.Contains("Evidence search query") -or `
            -not $phase15AgentsPage.Content.Contains("No public-web provider is configured")) {
        throw "Phase 16 protected research registry UI did not render"
    }
    Write-Output "Phase 16 research contract and SearchProvider smoke passed"

    # Phase 17 is deterministic here: inspect contracts and reject ungrounded
    # strategy creation without making a model-provider call.
    $phase17Strategist = $phase16Dashboard.definitions | Where-Object {
        $_.agent_id -eq "business-strategist"
    } | Select-Object -First 1
    $phase17RequiredArtifacts = @(
        "opportunity_assessment",
        "value_proposition",
        "business_model",
        "pricing_hypotheses",
        "positioning",
        "go_to_market",
        "launch_roadmap",
        "risks",
        "assumptions_requiring_validation"
    )
    if (-not $phase17Strategist -or `
            $phase17Strategist.version -ne 1 -or `
            $phase17Strategist.risk_level -ne "R0" -or `
            $phase17Strategist.maximum_autonomy -ne "manual_advisory_only" -or `
            @($phase17Strategist.allowed_tools).Count -ne 0 -or `
            @($phase17Strategist.allowed_skills).Count -ne 0 -or `
            $phase17Strategist.data_access_scope.research_evidence -ne `
                "explicit_completed_phase_16_runs_only" -or `
            @($phase17Strategist.input_schema.required) -notcontains `
                "strategy_evidence") {
        throw "Phase 17 strategist contract can exceed its evidence-bound advisory role"
    }
    foreach ($artifact in $phase17RequiredArtifacts) {
        if (@($phase17Strategist.output_schema.required) -notcontains $artifact) {
            throw "Phase 17 strategy schema is missing $artifact"
        }
    }
    Assert-HttpStatus -ExpectedStatus 422 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/agents/business-strategist/runs" `
            -Method Post `
            -Headers @{
                Origin = $smokePublicOrigin
                "X-CSRF-Token" = $csrfCookie.Value
            } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                    objective = "Propose an evidence-backed strategy"
                    research_run_ids = @()
                } | ConvertTo-Json -Depth 4 -Compress)
    }
    $phase17Dashboard = Invoke-RestMethod -Uri "$smokeApiOrigin/strategy" `
        -WebSession $ownerSession
    if ($phase17Dashboard.current_version -ne 0 -or `
            $phase17Dashboard.approved -or `
            @($phase17Dashboard.candidate_runs).Count -ne 0) {
        throw "Phase 17 approval domain did not begin in an explicit unapproved state"
    }
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/strategy/approve" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = "" } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                    run_id = "00000000-0000-0000-0000-000000001701"
                    expected_version = 0
                } | ConvertTo-Json -Compress)
    }
    $phase17Page = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/strategy" -WebSession $phase15WebSession
    if (-not $phase17Page.Content.Contains("Evidence first, founder approval second") -or `
            -not $phase17Page.Content.Contains("Not approved yet")) {
        throw "Phase 17 protected strategy review UI did not render"
    }
    Write-Output "Phase 17 strategy contract and approval-boundary smoke passed"

    # Phase 18 remains deterministic here: inspect the immutable advisory
    # contract and verify the approved-strategy and founder-approval boundaries.
    $phase18Agent = $phase16Dashboard.definitions | Where-Object {
        $_.agent_id -eq "product-offer"
    } | Select-Object -First 1
    $phase18RequiredArtifacts = @(
        "target_segments",
        "products_services",
        "packages"
    )
    if (-not $phase18Agent -or `
            $phase18Agent.version -ne 1 -or `
            $phase18Agent.risk_level -ne "R0" -or `
            $phase18Agent.maximum_autonomy -ne "manual_advisory_only" -or `
            @($phase18Agent.allowed_tools).Count -ne 0 -or `
            @($phase18Agent.allowed_skills).Count -ne 0 -or `
            $phase18Agent.data_access_scope.approved_strategy -ne `
                "required_exact_current_version" -or `
            @($phase18Agent.input_schema.required) -notcontains "offer_evidence") {
        throw "Phase 18 product and offer contract can exceed its advisory boundary"
    }
    foreach ($artifact in $phase18RequiredArtifacts) {
        if (@($phase18Agent.output_schema.required) -notcontains $artifact) {
            throw "Phase 18 product and offer schema is missing $artifact"
        }
    }
    Assert-HttpStatus -ExpectedStatus 422 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/agents/product-offer/runs" `
            -Method Post `
            -Headers @{
                Origin = $smokePublicOrigin
                "X-CSRF-Token" = $csrfCookie.Value
            } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                    objective = "Propose an approved-strategy-linked product portfolio"
                } | ConvertTo-Json -Depth 4 -Compress)
    }
    $phase18Dashboard = Invoke-RestMethod -Uri "$smokeApiOrigin/products-offers" `
        -WebSession $ownerSession
    if ($phase18Dashboard.current_version -ne 0 -or `
            $phase18Dashboard.current -or `
            @($phase18Dashboard.versions).Count -ne 0 -or `
            @($phase18Dashboard.candidate_runs).Count -ne 0) {
        throw "Phase 18 approval domain did not begin in an explicit unapproved state"
    }
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/products-offers/approve" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = "" } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                    run_id = "00000000-0000-0000-0000-000000001801"
                    expected_version = 0
                } | ConvertTo-Json -Compress)
    }
    $phase18Page = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/products-offers" -WebSession $phase15WebSession
    if (-not $phase18Page.Content.Contains("Traceable offers, explicit founder approval") -or `
            -not $phase18Page.Content.Contains("Not approved yet")) {
        throw "Phase 18 protected product and offer review UI did not render"
    }
    Write-Output "Phase 18 product and offer contract and approval-boundary smoke passed"

    # Phase 19 is deterministic here: inspect the immutable advisory contract
    # and verify the aligned strategy/offer and founder-approval boundaries.
    $phase19Agent = $phase16Dashboard.definitions | Where-Object {
        $_.agent_id -eq "brand-strategist"
    } | Select-Object -First 1
    $phase19RequiredArtifacts = @(
        "brand_strategy",
        "positioning",
        "naming_analysis",
        "voice",
        "messaging",
        "visual_direction",
        "brand_rules",
        "asset_references",
        "tagline"
    )
    if (-not $phase19Agent -or `
            $phase19Agent.version -ne 1 -or `
            $phase19Agent.risk_level -ne "R0" -or `
            $phase19Agent.maximum_autonomy -ne "manual_advisory_only" -or `
            @($phase19Agent.allowed_tools).Count -ne 0 -or `
            @($phase19Agent.allowed_skills).Count -ne 0 -or `
            $phase19Agent.data_access_scope.approved_strategy -ne `
                "required_exact_current_version" -or `
            $phase19Agent.data_access_scope.approved_product_offer -ne `
                "required_exact_active_version" -or `
            @($phase19Agent.input_schema.required) -notcontains "brand_evidence") {
        throw "Phase 19 Brand Strategist contract can exceed its advisory boundary"
    }
    foreach ($artifact in $phase19RequiredArtifacts) {
        if (@($phase19Agent.output_schema.required) -notcontains $artifact) {
            throw "Phase 19 brand schema is missing $artifact"
        }
    }
    Assert-HttpStatus -ExpectedStatus 422 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/agents/brand-strategist/runs" `
            -Method Post `
            -Headers @{
                Origin = $smokePublicOrigin
                "X-CSRF-Token" = $csrfCookie.Value
            } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                    objective = "Propose an approved-evidence-linked brand system"
                } | ConvertTo-Json -Depth 4 -Compress)
    }
    $phase19Dashboard = Invoke-RestMethod -Uri "$smokeApiOrigin/brand" `
        -WebSession $ownerSession
    if ($phase19Dashboard.current_version -ne 0 -or `
            $phase19Dashboard.current -or `
            @($phase19Dashboard.versions).Count -ne 0 -or `
            @($phase19Dashboard.candidate_runs).Count -ne 0) {
        throw "Phase 19 approval domain did not begin in an explicit unapproved state"
    }
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/brand/approve" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = "" } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{
                    run_id = "00000000-0000-0000-0000-000000001901"
                    expected_version = 0
                } | ConvertTo-Json -Compress)
    }
    $phase19Page = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/brand" -WebSession $phase15WebSession
    if (-not $phase19Page.Content.Contains("Approved rules, reusable brand direction") -or `
            -not $phase19Page.Content.Contains("Not approved yet")) {
        throw "Phase 19 protected brand review UI did not render"
    }
    Write-Output "Phase 19 brand contract and approval-boundary smoke passed"

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
    $liveGatewayResponse = Invoke-WithTransientHttpRetry -Request {
        Invoke-RestMethod -Uri "$smokeApiOrigin/ai/generate" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body $liveGatewayBody
    }
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
    if ($persistedGatewayDashboard.usage.calls -lt 1 -or `
            $persistedGatewayDashboard.usage.total_tokens -le 0 -or `
            $persistedGatewayDashboard.recent_calls.Count -lt 1) {
        throw "Successful live model usage was not persisted"
    }

    $agentDashboard = Invoke-RestMethod -Uri "$smokeApiOrigin/agents" `
        -WebSession $ownerSession
    $verificationAgent = $agentDashboard.definitions | Where-Object {
        $_.agent_id -eq "runtime-verification-agent"
    } | Select-Object -First 1
    $ceoAgent = $agentDashboard.definitions | Where-Object {
        $_.agent_id -eq "founder-ceo"
    } | Select-Object -First 1
    $planningAgent = $agentDashboard.definitions | Where-Object {
        $_.agent_id -eq "chief-of-staff-planning"
    } | Select-Object -First 1
    if ($agentDashboard.business_id -ne $businessBId -or `
            $agentDashboard.definitions.Count -ne 9 -or `
            -not $verificationAgent -or `
            $verificationAgent.version -ne 2 -or `
            $verificationAgent.risk_level -ne "R0" -or `
            $verificationAgent.maximum_autonomy -ne "manual_run_only" -or `
            $verificationAgent.allowed_skills.Count -ne 1 -or `
            $verificationAgent.allowed_skills[0] -ne `
                "summarize-business-context" -or `
            $verificationAgent.assigned_skills.Count -ne 1 -or `
            $verificationAgent.assigned_skills[0].skill_id -ne `
                "summarize-business-context" -or `
            $verificationAgent.allowed_tools.Count -ne 0) {
        throw "Versioned R0 agent definition or permission boundary is incorrect"
    }
    foreach ($executiveAgent in @($ceoAgent, $planningAgent)) {
        if (-not $executiveAgent -or `
                $executiveAgent.version -ne 1 -or `
                $executiveAgent.risk_level -ne "R0" -or `
                $executiveAgent.maximum_autonomy -ne "manual_advisory_only" -or `
                @($executiveAgent.allowed_tools).Count -ne 0 -or `
                @($executiveAgent.allowed_skills).Count -ne 0 -or `
                @($executiveAgent.assigned_skills).Count -ne 0 -or `
                @($executiveAgent.data_access_scope.sources) -notcontains "current_tasks" -or `
                @($executiveAgent.data_access_scope.sources) -notcontains "relevant_memories" -or `
                @($executiveAgent.forbidden_actions) -notcontains "Tool invocation" -or `
                @($executiveAgent.forbidden_actions) -notcontains `
                    "Creating, updating, queueing, or completing tasks or workflows") {
            throw "Phase 15 executive contract can exceed its advisory boundary"
        }
    }
    if (@($ceoAgent.output_schema.required) -notcontains "priorities" -or `
            @($planningAgent.output_schema.required) -notcontains "tasks") {
        throw "Phase 15 executive traceable plan schemas are incomplete"
    }
    $summarySkill = $agentDashboard.skills | Where-Object {
        $_.skill_id -eq "summarize-business-context"
    } | Select-Object -First 1
    if (@($agentDashboard.skills).Count -ne 3 -or `
            -not $summarySkill -or `
            $summarySkill.risk_class -ne "R0" -or `
            @($summarySkill.tool_requirements).Count -ne 0 -or `
            @($summarySkill.compatible_agents) -notcontains `
                "runtime-verification-agent" -or `
            @($summarySkill.test_fixtures).Count -lt 1 -or `
            @($summarySkill.evaluation_rubric).Count -lt 1) {
        throw "Immutable skill registry metadata is incomplete"
    }
    $agentRunBody = @{
        objective = "Inspect the selected business context and return one grounded observation."
        skill_id = "summarize-business-context"
        skill_input = @{ focus = "Identify one supported business observation" }
    } | ConvertTo-Json -Compress
    $unassignedSkillBody = @{
        objective = "Generate a plan"
        skill_id = "generate-structured-plan"
        skill_input = @{ goal = "Prepare launch"; constraints = @() }
    } | ConvertTo-Json -Compress
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/agents/runtime-verification-agent/runs" `
            -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body $unassignedSkillBody
    }
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/agents/runtime-verification-agent/runs" `
            -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = "" } `
            -ContentType "application/json" -WebSession $ownerSession -Body $agentRunBody
    }
    Assert-HttpStatus -ExpectedStatus 403 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/agents/founder-ceo/runs" `
            -Method Post -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = "" } `
            -ContentType "application/json" -WebSession $ownerSession `
            -Body (@{ objective = "Propose priorities" } | ConvertTo-Json -Compress)
    }
    $transientAgentFailures = 0
    $completedAgentRun = $null
    foreach ($agentAttempt in 1..3) {
        $agentRun = Invoke-RestMethod `
            -Uri "$smokeApiOrigin/agents/runtime-verification-agent/runs" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession -Body $agentRunBody
        if ($agentRun.business_id -ne $businessBId -or `
                $agentRun.skill_id -ne "summarize-business-context" -or `
                $agentRun.skill_version -ne 1 -or `
                $agentRun.status -notin @("queued", "running", "completed")) {
            throw "Agent run was not durably queued for the selected business"
        }
        $completedAgentRun = Wait-ForAgentRun `
            -Uri "$smokeApiOrigin/agents/runs/$($agentRun.id)" -WebSession $ownerSession
        if ($completedAgentRun.status -eq "completed") { break }
        $isTransientProviderFailure = $completedAgentRun.error_type -match `
            '^provider_(http_(408|409|425|429|5[0-9][0-9])|timeout|transport)$'
        if (-not $isTransientProviderFailure -or $agentAttempt -eq 3) { break }
        $transientAgentFailures += 1
        Start-Sleep -Seconds (20 * $agentAttempt)
    }
    $agentInput = $completedAgentRun.structured_input | ConvertTo-Json -Depth 30 -Compress
    if ($completedAgentRun.status -ne "completed" -or `
            -not $completedAgentRun.structured_output.summary -or `
            $completedAgentRun.structured_output.observations.Count -gt 5 -or `
            $completedAgentRun.usage.calls -lt 1 -or `
            $completedAgentRun.usage.total_tokens -le 0 -or `
            $completedAgentRun.usage.estimated_cost_microusd -gt 10000 -or `
            -not $completedAgentRun.model_operation_id -or `
            $completedAgentRun.skill_id -ne "summarize-business-context" -or `
            $completedAgentRun.skill_version -ne 1 -or `
            -not $completedAgentRun.skill_version_id -or `
            -not ($completedAgentRun.usage.attempts | Where-Object {
                    $_.operation_id -eq $completedAgentRun.model_operation_id
                }) -or `
            -not $agentInput.Contains("Beta-only goal") -or `
            $agentInput.Contains("Alpha-only goal")) {
        throw "Agent did not execute end-to-end with structured isolated context and usage"
    }

    Invoke-Checked { docker pause $smokeWorkerContainer }
    try {
        $cancelRun = Invoke-RestMethod `
            -Uri "$smokeApiOrigin/agents/runtime-verification-agent/runs" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession -Body $agentRunBody
        $cancelledRun = Invoke-RestMethod `
            -Uri "$smokeApiOrigin/agents/runs/$($cancelRun.id)/cancel" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -WebSession $ownerSession
        if ($cancelledRun.status -ne "cancelled" -or `
                -not $cancelledRun.cancellation_requested_at -or `
                -not $cancelledRun.cancelled_at -or $cancelledRun.structured_output) {
            throw "Queued agent cancellation was not persisted"
        }

        $failureRun = Invoke-RestMethod `
            -Uri "$smokeApiOrigin/agents/runtime-verification-agent/runs" -Method Post `
            -Headers @{ Origin = $smokePublicOrigin; "X-CSRF-Token" = $csrfCookie.Value } `
            -ContentType "application/json" -WebSession $ownerSession -Body $agentRunBody
        docker compose exec -T postgres psql -U foundora -d $smokeDatabase `
            -tAc "UPDATE agent_runs SET structured_input = '{}'::json WHERE id = '$($failureRun.id)'" `
            | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not prepare deterministic failed agent run" }
    }
    finally {
        Invoke-Checked { docker unpause $smokeWorkerContainer }
    }
    $failedAgentRun = Wait-ForAgentRun `
        -Uri "$smokeApiOrigin/agents/runs/$($failureRun.id)" -WebSession $ownerSession
    if ($failedAgentRun.status -ne "failed" -or `
            $failedAgentRun.error_type -ne "agent_schema_invalid" -or `
            -not $failedAgentRun.error_message -or $failedAgentRun.structured_output) {
        throw "Agent runtime failure was not persisted honestly"
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
    Assert-HttpStatus -ExpectedStatus 404 -Request {
        Invoke-WebRequest -UseBasicParsing `
            -Uri "$smokeApiOrigin/agents/runs/$($agentRun.id)" `
            -WebSession $ownerWebSession
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
    $webAgentsPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/agents" -WebSession $ownerWebSession
    if (-not $webAgentsPage.Content.Contains("Assigned capability, inspectable execution") -or `
            -not $webAgentsPage.Content.Contains("Runtime Verification Agent") -or `
            -not $webAgentsPage.Content.Contains("Founder / CEO Agent") -or `
            -not $webAgentsPage.Content.Contains("Chief-of-Staff / Planning Agent") -or `
            -not $webAgentsPage.Content.Contains("Queue manual R0 advisory run") -or `
            -not $webAgentsPage.Content.Contains("Summarize Business Context") -or `
            -not $webAgentsPage.Content.Contains("Generate Structured Plan") -or `
            -not $webAgentsPage.Content.Contains("Analyze Provided Data")) {
        throw "Protected agent registry and permission boundary did not render"
    }
    $webTasksPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/tasks" -WebSession $ownerWebSession
    if (-not $webTasksPage.Content.Contains("Durable work, explicit dependencies") -or `
            -not $webTasksPage.Content.Contains("Persist draft task") -or `
            -not $webTasksPage.Content.Contains("Tasks by priority and due date")) {
        throw "Protected task ledger did not render"
    }
    $webWorkflowsPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/workflows" -WebSession $ownerWebSession
    if (-not $webWorkflowsPage.Content.Contains("Versioned execution, durable checkpoints") -or `
            -not $webWorkflowsPage.Content.Contains("Durable checkpoint verification") -or `
            -not $webWorkflowsPage.Content.Contains("Start pinned workflow")) {
        throw "Protected workflow registry and execution controls did not render"
    }
    $webGovernancePage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/governance" -WebSession $ownerWebSession
    if (-not $webGovernancePage.Content.Contains("Policy, risk, approvals, and hard stops") -or `
            -not $webGovernancePage.Content.Contains("Global kill switch") -or `
            -not $webGovernancePage.Content.Contains("Propose an authorization") -or `
            -not $webGovernancePage.Content.Contains("Governance audit trail")) {
        throw "Protected governance controls and audit ledger did not render"
    }
    $webEventsPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/events" -WebSession $ownerWebSession
    if (-not $webEventsPage.Content.Contains("Durable domain events and handler deliveries") -or `
            -not $webEventsPage.Content.Contains("Registered event routes") -or `
            -not $webEventsPage.Content.Contains("business.created")) {
        throw "Protected Phase 12 event ledger did not render real registered contracts"
    }
    $webKnowledgePage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/knowledge" -WebSession $ownerWebSession
    if (-not $webKnowledgePage.Content.Contains("Retrievable evidence with durable citations") -or `
            -not $webKnowledgePage.Content.Contains("Record provenance first") -or `
            -not $webKnowledgePage.Content.Contains("Search active knowledge")) {
        throw "Protected Phase 13 knowledge ingestion and retrieval UI did not render"
    }
    $webMemoryPage = Invoke-WebRequest -UseBasicParsing `
        -Uri "$smokePublicOrigin/memory" -WebSession $ownerWebSession
    if (-not $webMemoryPage.Content.Contains("Curated memory with visible provenance") -or `
            -not $webMemoryPage.Content.Contains("Founder review is the safe default") -or `
            -not $webMemoryPage.Content.Contains("Durable memory ledger")) {
        throw "Protected Phase 14 curator, policy, and provenance UI did not render"
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
    if ($LASTEXITCODE -ne 0 -or $smokeVersion.Trim() -ne "20260825_19") {
        throw "Isolated brand-system migration is not current"
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
    $knowledgeEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM knowledge_sources WHERE business_id = '$businessBId') || '|' || (SELECT count(*) FROM knowledge_documents WHERE id = '$knowledgeDocumentId' AND status = 'indexed' AND chunk_count > 0) || '|' || (SELECT count(*) FROM document_chunks WHERE document_id = '$knowledgeDocumentId' AND embedding_model = 'foundora.local-feature-hash.v1') || '|' || (SELECT count(*) FROM knowledge_sources WHERE id = '$invalidatedSourceId' AND status = 'invalidated') || '|' || (SELECT count(*) FROM knowledge_documents WHERE id = '$invalidatedDocumentId' AND status = 'invalidated')"
    $knowledgeEvidenceParts = $knowledgeEvidence.Trim().Split("|")
    if ($LASTEXITCODE -ne 0 -or $knowledgeEvidenceParts.Count -ne 5 -or `
            [int]$knowledgeEvidenceParts[0] -ne 2 -or `
            [int]$knowledgeEvidenceParts[1] -ne 1 -or `
            [int]$knowledgeEvidenceParts[2] -lt 1 -or `
            [int]$knowledgeEvidenceParts[3] -ne 1 -or `
            [int]$knowledgeEvidenceParts[4] -ne 1) {
        throw "Phase 13 source, document, chunk, embedding, or invalidation evidence is incorrect"
    }
    $memoryEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM memory_proposals WHERE business_id = '$businessBId') || '|' || (SELECT count(*) FROM memory_records WHERE business_id = '$businessBId') || '|' || (SELECT count(*) FROM memory_revisions WHERE business_id = '$businessBId') || '|' || (SELECT count(*) FROM memory_provenance WHERE business_id = '$businessBId') || '|' || (SELECT count(*) FROM memory_records WHERE id = '$factMemoryId' AND epistemic_status = 'fact' AND accepted_via = 'founder' AND status = 'active') || '|' || (SELECT count(*) FROM memory_records WHERE originating_proposal_id = '$($automaticMemory.id)' AND accepted_via = 'automatic' AND status = 'active') || '|' || (SELECT count(*) FROM memory_records WHERE id = '$memoryId' AND status = 'invalidated' AND current_revision = 3)"
    if ($LASTEXITCODE -ne 0 -or $memoryEvidence.Trim() -ne "4|3|4|4|1|1|1") {
        throw "Phase 14 policy, acceptance, merge, provenance, or invalidation evidence is incorrect"
    }
    $executiveEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM agents WHERE id IN ('founder-ceo', 'chief-of-staff-planning') AND enabled = true AND current_version = 1) || '|' || (SELECT count(*) FROM agent_versions WHERE agent_id IN ('founder-ceo', 'chief-of-staff-planning') AND risk_level = 'R0' AND maximum_autonomy = 'manual_advisory_only' AND json_array_length(allowed_tools) = 0 AND json_array_length(allowed_skills) = 0)"
    if ($LASTEXITCODE -ne 0 -or $executiveEvidence.Trim() -ne "2|2") {
        throw "Phase 15 immutable advisory executive contracts are incorrect"
    }
    $researchEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM agents WHERE id IN ('market-research', 'competitor-intelligence', 'customer-research') AND enabled = true AND current_version = 1) || '|' || (SELECT count(*) FROM agent_versions WHERE agent_id IN ('market-research', 'competitor-intelligence', 'customer-research') AND risk_level = 'R0' AND maximum_autonomy = 'manual_advisory_only' AND json_array_length(allowed_tools) = 0 AND json_array_length(allowed_skills) = 0 AND data_access_scope->>'research_evidence' = 'explicit_search_provider_results_only')"
    if ($LASTEXITCODE -ne 0 -or $researchEvidence.Trim() -ne "3|3") {
        throw "Phase 16 immutable source-backed research contracts are incorrect"
    }
    $strategyEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM agents WHERE id = 'business-strategist' AND enabled = true AND current_version = 1) || '|' || (SELECT count(*) FROM agent_versions WHERE agent_id = 'business-strategist' AND risk_level = 'R0' AND maximum_autonomy = 'manual_advisory_only' AND json_array_length(allowed_tools) = 0 AND json_array_length(allowed_skills) = 0 AND data_access_scope->>'research_evidence' = 'explicit_completed_phase_16_runs_only') || '|' || (SELECT count(*) FROM approved_business_strategies)"
    if ($LASTEXITCODE -ne 0 -or $strategyEvidence.Trim() -ne "1|1|0") {
        throw "Phase 17 strategist or explicit approval-domain evidence is incorrect"
    }
    $productOfferEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM agents WHERE id = 'product-offer' AND enabled = true AND current_version = 1) || '|' || (SELECT count(*) FROM agent_versions WHERE agent_id = 'product-offer' AND risk_level = 'R0' AND maximum_autonomy = 'manual_advisory_only' AND json_array_length(allowed_tools) = 0 AND json_array_length(allowed_skills) = 0 AND data_access_scope->>'approved_strategy' = 'required_exact_current_version') || '|' || (SELECT count(*) FROM product_offer_versions)"
    if ($LASTEXITCODE -ne 0 -or $productOfferEvidence.Trim() -ne "1|1|0") {
        throw "Phase 18 product and offer agent or approval-domain evidence is incorrect"
    }
    $brandEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM agents WHERE id = 'brand-strategist' AND enabled = true AND current_version = 1) || '|' || (SELECT count(*) FROM agent_versions WHERE agent_id = 'brand-strategist' AND risk_level = 'R0' AND maximum_autonomy = 'manual_advisory_only' AND json_array_length(allowed_tools) = 0 AND json_array_length(allowed_skills) = 0 AND data_access_scope->>'approved_strategy' = 'required_exact_current_version' AND data_access_scope->>'approved_product_offer' = 'required_exact_active_version') || '|' || (SELECT count(*) FROM brand_system_versions)"
    if ($LASTEXITCODE -ne 0 -or $brandEvidence.Trim() -ne "1|1|0") {
        throw "Phase 19 Brand Strategist or approval-domain evidence is incorrect"
    }
    $taskEngineEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM tasks WHERE business_id = '$businessBId') || '|' || (SELECT count(*) FROM task_dependencies) || '|' || (SELECT count(*) FROM task_events WHERE task_id = '$dependentTaskId' AND event_type = 'retried') || '|' || (SELECT retry_count FROM tasks WHERE id = '$dependentTaskId')"
    if ($LASTEXITCODE -ne 0 -or $taskEngineEvidence.Trim() -ne "2|1|1|1") {
        throw "Durable task, dependency, event, or idempotent retry evidence is incorrect"
    }
    $workflowEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM workflow_runs WHERE id = '$workflowRunId' AND business_id = '$businessBId' AND status = 'completed') || '|' || (SELECT count(*) FROM workflow_step_runs WHERE workflow_run_id = '$workflowRunId' AND status = 'completed') || '|' || (SELECT count(*) FROM workflow_events WHERE workflow_run_id = '$workflowRunId' AND event_type = 'owner_resumed')"
    if ($LASTEXITCODE -ne 0 -or $workflowEvidence.Trim() -ne "1|5|2") {
        throw "Durable workflow run, steps, or idempotent resume evidence is incorrect"
    }
    $workflowFailureEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM workflow_runs WHERE id = '$rejectedWorkflowId' AND status = 'failed' AND error_type = 'checkpoint_rejected') || '|' || (SELECT count(*) FROM workflow_step_runs WHERE workflow_run_id = '$rejectedWorkflowId' AND status = 'compensated') || '|' || (SELECT count(*) FROM workflow_events WHERE workflow_run_id = '$rejectedWorkflowId' AND event_type = 'step_compensated')"
    if ($LASTEXITCODE -ne 0 -or $workflowFailureEvidence.Trim() -ne "1|1|1") {
        throw "Deterministic workflow failure or compensation evidence is incorrect"
    }
    $governanceEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM governance_actions WHERE business_id = '$businessBId' AND risk_class IN ('R3', 'R4') AND status = 'authorized') || '|' || (SELECT count(*) FROM governance_actions WHERE business_id = '$businessBId' AND status = 'rejected') || '|' || (SELECT count(*) FROM governance_audit_events WHERE business_id = '$businessBId' AND event_type = 'execution_denied') || '|' || (SELECT count(*) FROM governance_audit_events WHERE business_id IS NULL AND event_type IN ('kill_switch_engaged', 'kill_switch_released')) || '|' || (SELECT count(*) FROM workflow_runs WHERE id IN ('$disabledToolWorkflowId', '$killedWorkflowId') AND status = 'failed' AND error_type = 'governance_denied')"
    $governanceEvidenceParts = $governanceEvidence.Trim().Split("|")
    if ($LASTEXITCODE -ne 0 -or $governanceEvidenceParts.Count -ne 5 -or `
            [int]$governanceEvidenceParts[0] -ne 2 -or `
            [int]$governanceEvidenceParts[1] -lt 2 -or `
            [int]$governanceEvidenceParts[2] -lt 2 -or `
            [int]$governanceEvidenceParts[3] -ne 2 -or `
            [int]$governanceEvidenceParts[4] -ne 2) {
        throw "Phase 11 approval, rejection, audit, tool, or kill-switch evidence is incorrect"
    }
    $eventBusEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM domain_events WHERE business_id = '$businessBId' AND event_type IN ('business.created', 'goal.created', 'task.completed', 'task.failed')) || '|' || (SELECT count(*) FROM domain_events WHERE business_id = '$businessBId' AND event_type = 'approval.requested') || '|' || (SELECT count(*) FROM event_deliveries d JOIN domain_events e ON e.id = d.event_id WHERE e.business_id = '$businessBId' AND d.consumer_name = 'foundora.event-audit.v1' AND d.status = 'completed' AND d.attempt_count = 1) || '|' || (SELECT count(*) FROM event_deliveries WHERE id = '$deadLetterDeliveryId' AND status = 'dead_letter' AND attempt_count = 1 AND redrive_count = 1) || '|' || (SELECT count(*) FROM (SELECT business_id, event_type, idempotency_key FROM domain_events GROUP BY business_id, event_type, idempotency_key HAVING count(*) > 1) duplicates)"
    $eventBusEvidenceParts = $eventBusEvidence.Trim().Split("|")
    if ($LASTEXITCODE -ne 0 -or $eventBusEvidenceParts.Count -ne 5 -or `
            [int]$eventBusEvidenceParts[0] -ne 4 -or `
            [int]$eventBusEvidenceParts[1] -lt 3 -or `
            [int]$eventBusEvidenceParts[2] -lt 7 -or `
            [int]$eventBusEvidenceParts[3] -ne 1 -or `
            [int]$eventBusEvidenceParts[4] -ne 0) {
        throw "Phase 12 event, idempotent delivery, or dead-letter evidence is incorrect"
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
            [int]$gatewayUsageParts[0] -lt 2 -or [int]$gatewayUsageParts[1] -ne 2 -or `
            [int]$gatewayUsageParts[2] -le 0) {
        throw "Persisted model usage evidence is incorrect"
    }
    $agentRunEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT count(*) || '|' || count(*) FILTER (WHERE status = 'completed') || '|' || count(*) FILTER (WHERE status = 'failed') || '|' || count(*) FILTER (WHERE status = 'cancelled') FROM agent_runs WHERE business_id = '$businessBId'"
    $expectedAgentRuns = 3 + $transientAgentFailures
    $expectedFailedAgentRuns = 1 + $transientAgentFailures
    $expectedAgentRunEvidence = `
        "$expectedAgentRuns|1|$expectedFailedAgentRuns|1"
    if ($LASTEXITCODE -ne 0 -or `
            $agentRunEvidence.Trim() -ne $expectedAgentRunEvidence) {
        throw "Durable agent lifecycle evidence is incorrect"
    }
    $agentUsageEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT count(*) || '|' || count(*) FILTER (WHERE status = 'succeeded') FROM model_gateway_calls WHERE agent_run_id = '$($agentRun.id)'"
    $agentUsageParts = $agentUsageEvidence.Trim().Split("|")
    if ($LASTEXITCODE -ne 0 -or $agentUsageParts.Count -ne 2 -or `
            [int]$agentUsageParts[0] -lt 1 -or [int]$agentUsageParts[1] -ne 1) {
        throw "Agent-to-model usage linkage evidence is incorrect"
    }
    $agentContractEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT count(*) || '|' || min(current_version) FROM agents WHERE id = 'runtime-verification-agent' AND enabled = true"
    if ($LASTEXITCODE -ne 0 -or $agentContractEvidence.Trim() -ne "1|2") {
        throw "Versioned agent registry evidence is incorrect"
    }
    $skillContractEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT (SELECT count(*) FROM skills) || '|' || (SELECT count(*) FROM skill_versions) || '|' || (SELECT count(*) FROM agent_skill_assignments)"
    if ($LASTEXITCODE -ne 0 -or $skillContractEvidence.Trim() -ne "3|3|1") {
        throw "Skill registry or exact-version assignment evidence is incorrect"
    }
    $skillRunEvidence = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc `
        "SELECT count(*) FROM agent_runs r JOIN skill_versions s ON s.id = r.skill_version_id WHERE r.id = '$($agentRun.id)' AND s.skill_id = 'summarize-business-context' AND s.version = 1"
    if ($LASTEXITCODE -ne 0 -or $skillRunEvidence.Trim() -ne "1") {
        throw "Successful agent run was not pinned to its skill version"
    }
    $providerValidationCount = docker compose exec -T postgres psql -U foundora `
        -d $smokeDatabase -tAc "SELECT count(*) FROM model_provider_validations"
    if ($LASTEXITCODE -ne 0 -or $providerValidationCount.Trim() -ne "3") {
        throw "Expected all provider validation outcomes to be persisted"
    }
}
catch {
    $smokeFailure = $_
    $priorErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    if ($smokeApiContainer) { docker logs --tail 120 $smokeApiContainer 2>&1 | Out-Host }
    if ($smokeWorkerContainer) { docker logs --tail 120 $smokeWorkerContainer 2>&1 | Out-Host }
    $ErrorActionPreference = $priorErrorPreference
    throw $smokeFailure
}
finally {
    if ($smokeWorkerContainer) {
        docker rm --force $smokeWorkerContainer 2>$null | Out-Null
    }
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
    $agentRunBody = $null
    $unassignedSkillBody = $null
    $transientAgentFailures = $null
    $phase15LoginResponse = $null
    $phase15CsrfCookie = $null
    $phase15AgentsPage = $null
    $phase15WebSession = $null
    $phase16Dashboard = $null
    $phase16Search = $null
    $phase16Evidence = $null
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
if ($LASTEXITCODE -ne 0 -or $migrationVersion.Trim() -ne "20260825_19") {
    throw "Brand-system migration is not current"
}
Invoke-Checked { docker compose exec -T worker python -m foundora.worker_health }

Invoke-Checked { docker compose ps }
