"use server";

import { redirect } from "next/navigation";

import {
  adoptAuthCookies,
  authenticatedApiRequest,
  authenticatedApiUpload,
  clearAuthCookies,
  loginApiRequest,
  modelRequestTimeoutMs,
} from "../lib/auth";

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

export async function login(formData: FormData): Promise<never> {
  let response: Response;
  try {
    response = await loginApiRequest(
      field(formData, "email"),
      field(formData, "password"),
    );
  } catch {
    redirect("/login?error=unavailable");
  }
  if (!response.ok) {
    redirect(
      response.status === 429 ? "/login?error=limited" : "/login?error=invalid",
    );
  }
  if (!(await adoptAuthCookies(response))) {
    redirect("/login?error=unavailable");
  }
  redirect("/workspace");
}

function workspaceError(response: Response): string {
  if (response.status === 401) return "session";
  if (response.status === 409) return "conflict";
  if (response.status === 422) return "invalid";
  return "unavailable";
}

async function workspaceMutation(
  path: string,
  body: Record<string, unknown> | undefined,
): Promise<Response> {
  try {
    return await authenticatedApiRequest(path, body);
  } catch {
    redirect("/workspace?error=unavailable");
  }
}

export async function createBusiness(formData: FormData): Promise<never> {
  const response = await workspaceMutation("/businesses", {
    name: field(formData, "name"),
    summary: field(formData, "summary"),
  });
  if (!response.ok) redirect(`/workspace?error=${workspaceError(response)}`);
  redirect("/workspace?updated=created");
}

export async function selectBusiness(formData: FormData): Promise<never> {
  const response = await workspaceMutation("/businesses/select", {
    business_id: field(formData, "business_id"),
  });
  if (!response.ok) redirect(`/workspace?error=${workspaceError(response)}`);
  redirect("/workspace?updated=selected");
}

export async function updateBusinessProfile(
  formData: FormData,
): Promise<never> {
  const response = await workspaceMutation("/workspace/profile", {
    name: field(formData, "name"),
    summary: field(formData, "summary"),
  });
  if (!response.ok) redirect(`/workspace?error=${workspaceError(response)}`);
  redirect("/workspace?updated=profile");
}

export async function updateBusinessStatus(formData: FormData): Promise<never> {
  const response = await workspaceMutation("/workspace/status", {
    status: field(formData, "status"),
  });
  if (!response.ok) redirect(`/workspace?error=${workspaceError(response)}`);
  redirect("/workspace?updated=status");
}

export async function updateBusinessPreferences(
  formData: FormData,
): Promise<never> {
  const response = await workspaceMutation("/workspace/preferences", {
    timezone: field(formData, "timezone"),
    currency: field(formData, "currency"),
    locale: field(formData, "locale"),
  });
  if (!response.ok) redirect(`/workspace?error=${workspaceError(response)}`);
  redirect("/workspace?updated=preferences");
}

export async function addBusinessGoal(formData: FormData): Promise<never> {
  const targetDate = field(formData, "target_date");
  const response = await workspaceMutation("/workspace/goals", {
    title: field(formData, "title"),
    details: field(formData, "details"),
    target_date: targetDate || null,
  });
  if (!response.ok) redirect(`/workspace?error=${workspaceError(response)}`);
  redirect("/workspace?updated=goal");
}

export async function updateBusinessGoalStatus(
  goalId: string,
  formData: FormData,
): Promise<never> {
  const response = await workspaceMutation(
    `/workspace/goals/${encodeURIComponent(goalId)}/status`,
    { status: field(formData, "status") },
  );
  if (!response.ok) redirect(`/workspace?error=${workspaceError(response)}`);
  redirect("/workspace?updated=goal");
}

export async function archiveBusiness(formData: FormData): Promise<never> {
  if (field(formData, "confirmation") !== "ARCHIVE") {
    redirect("/workspace?error=archive-confirmation");
  }
  const response = await workspaceMutation("/workspace/archive", undefined);
  if (!response.ok) redirect(`/workspace?error=${workspaceError(response)}`);
  redirect("/workspace?updated=archived");
}

function lines(formData: FormData, name: string): string[] {
  return field(formData, name)
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
}

async function onboardingMutation(
  path: string,
  body: Record<string, unknown>,
): Promise<Response> {
  try {
    return await authenticatedApiRequest(path, body);
  } catch {
    redirect("/onboarding?error=unavailable");
  }
}

function onboardingFailure(response: Response): never {
  redirect(
    `/onboarding?error=${response.status === 409 ? "conflict" : response.status === 422 ? "incomplete" : "unavailable"}`,
  );
}

export async function saveOnboardingFoundation(
  formData: FormData,
): Promise<never> {
  const response = await onboardingMutation("/onboarding/steps/foundation", {
    revision: field(formData, "revision"),
    business_type: field(formData, "business_type"),
    business_name: field(formData, "business_name"),
    industry: field(formData, "industry"),
    geography: field(formData, "geography"),
  });
  if (!response.ok) onboardingFailure(response);
  redirect("/onboarding?step=2&updated=saved");
}

export async function saveOnboardingMarket(formData: FormData): Promise<never> {
  const response = await onboardingMutation("/onboarding/steps/market", {
    revision: field(formData, "revision"),
    problem: field(formData, "problem"),
    target_audience: field(formData, "target_audience"),
    offer: field(formData, "offer"),
  });
  if (!response.ok) onboardingFailure(response);
  redirect("/onboarding?step=3&updated=saved");
}

export async function saveOnboardingExecution(
  formData: FormData,
): Promise<never> {
  const response = await onboardingMutation("/onboarding/steps/execution", {
    revision: field(formData, "revision"),
    goals: lines(formData, "goals"),
    existing_assets: lines(formData, "existing_assets"),
    constraints: lines(formData, "constraints"),
    budget: field(formData, "budget"),
  });
  if (!response.ok) onboardingFailure(response);
  redirect("/onboarding?step=4&updated=saved");
}

export async function saveOnboardingBrandServices(
  formData: FormData,
): Promise<never> {
  const response = await onboardingMutation(
    "/onboarding/steps/brand-services",
    {
      revision: field(formData, "revision"),
      brand_preferences: field(formData, "brand_preferences"),
      connected_services: lines(formData, "connected_services"),
    },
  );
  if (!response.ok) onboardingFailure(response);
  redirect("/onboarding?step=5&updated=saved");
}

export async function submitOnboarding(formData: FormData): Promise<never> {
  const response = await onboardingMutation("/onboarding/submit", {
    revision: field(formData, "revision"),
  });
  if (!response.ok) onboardingFailure(response);
  redirect("/onboarding?updated=submitted");
}

export async function approveOnboarding(formData: FormData): Promise<never> {
  const response = await onboardingMutation("/onboarding/approve", {
    revision: field(formData, "revision"),
  });
  if (!response.ok) onboardingFailure(response);
  redirect("/onboarding?updated=approved");
}

export async function reopenOnboarding(formData: FormData): Promise<never> {
  const response = await onboardingMutation("/onboarding/reopen", {
    revision: field(formData, "revision"),
  });
  if (!response.ok) onboardingFailure(response);
  redirect("/onboarding?step=1&updated=reopened");
}

export async function validateModelProvider(
  formData: FormData,
): Promise<never> {
  const provider = field(formData, "provider");
  if (!["openai", "gemini", "anthropic"].includes(provider)) {
    redirect("/settings/ai?error=provider");
  }
  let response: Response;
  try {
    response = await authenticatedApiRequest(
      `/ai/providers/${encodeURIComponent(provider)}/validate`,
      {},
      { timeoutMs: modelRequestTimeoutMs() },
    );
  } catch {
    redirect("/settings/ai?error=unavailable");
  }
  if (!response.ok) redirect("/settings/ai?error=provider");
  redirect("/settings/ai?updated=validated");
}

export async function runModelGatewayCheck(): Promise<never> {
  let response: Response;
  try {
    response = await authenticatedApiRequest(
      "/ai/generate",
      {
        task_type: "gateway.acceptance",
        prompt: "Reply with exactly FOUNDORA_GATEWAY_OK and nothing else.",
        system_prompt: "Follow the requested output format exactly.",
        sensitivity: "standard",
        allow_fallback: true,
        max_output_tokens: 32,
        token_budget: 1024,
        cost_budget_microusd: 2000,
      },
      { timeoutMs: modelRequestTimeoutMs() },
    );
  } catch {
    redirect("/settings/ai?error=unavailable");
  }
  if (!response.ok) {
    const code =
      response.status === 503
        ? "disabled"
        : response.status === 422
          ? "budget"
          : "provider";
    redirect(`/settings/ai?error=${code}`);
  }
  redirect("/settings/ai?updated=generated");
}

export async function runAgent(formData: FormData): Promise<never> {
  const agentId = field(formData, "agent_id");
  const skillId = field(formData, "skill_id");
  let skillInput: Record<string, unknown> = {};
  if (skillId) {
    try {
      const parsed: unknown = JSON.parse(field(formData, "skill_input"));
      if (
        typeof parsed !== "object" ||
        parsed === null ||
        Array.isArray(parsed)
      ) {
        redirect("/agents?error=invalid");
      }
      skillInput = parsed as Record<string, unknown>;
    } catch {
      redirect("/agents?error=invalid");
    }
  }
  let response: Response;
  try {
    response = await authenticatedApiRequest(
      `/agents/${encodeURIComponent(agentId)}/runs`,
      {
        objective: field(formData, "objective"),
        skill_id: skillId || null,
        skill_input: skillInput,
        research_query: field(formData, "research_query") || null,
        research_run_ids: formData
          .getAll("research_run_ids")
          .filter((value): value is string => typeof value === "string"),
      },
    );
  } catch {
    redirect("/agents?error=unavailable");
  }
  if (!response.ok) {
    redirect(
      `/agents?error=${response.status === 422 ? "invalid" : response.status === 403 ? "skill" : response.status === 404 ? "agent" : "unavailable"}`,
    );
  }
  const value: unknown = await response.json();
  if (
    typeof value !== "object" ||
    value === null ||
    typeof (value as { id?: unknown }).id !== "string"
  ) {
    redirect("/agents?error=unavailable");
  }
  redirect(`/agents?run=${(value as { id: string }).id}&updated=queued`);
}

export async function cancelAgentRun(runId: string): Promise<never> {
  let response: Response;
  try {
    response = await authenticatedApiRequest(
      `/agents/runs/${encodeURIComponent(runId)}/cancel`,
      undefined,
    );
  } catch {
    redirect(`/agents?run=${encodeURIComponent(runId)}&error=unavailable`);
  }
  if (!response.ok) {
    redirect(
      `/agents?run=${encodeURIComponent(runId)}&error=${response.status === 409 ? "terminal" : "unavailable"}`,
    );
  }
  redirect(`/agents?run=${encodeURIComponent(runId)}&updated=cancelled`);
}

export async function approveStrategy(formData: FormData): Promise<never> {
  let response: Response;
  try {
    response = await authenticatedApiRequest("/strategy/approve", {
      run_id: field(formData, "run_id"),
      expected_version: Number(field(formData, "expected_version")),
    });
  } catch {
    redirect("/strategy?error=unavailable");
  }
  if (!response.ok) {
    redirect(
      `/strategy?error=${response.status === 409 ? "conflict" : response.status === 422 ? "invalid" : "unavailable"}`,
    );
  }
  redirect("/strategy?updated=approved");
}

export async function approveProductOffer(formData: FormData): Promise<never> {
  let response: Response;
  try {
    response = await authenticatedApiRequest("/products-offers/approve", {
      run_id: field(formData, "run_id"),
      expected_version: Number(field(formData, "expected_version")),
    });
  } catch {
    redirect("/products-offers?error=unavailable");
  }
  if (!response.ok) {
    redirect(
      `/products-offers?error=${response.status === 409 ? "conflict" : response.status === 422 ? "invalid" : "unavailable"}`,
    );
  }
  redirect("/products-offers?updated=approved");
}

export async function approveBrand(formData: FormData): Promise<never> {
  let response: Response;
  try {
    response = await authenticatedApiRequest("/brand/approve", {
      run_id: field(formData, "run_id"),
      expected_version: Number(field(formData, "expected_version")),
    });
  } catch {
    redirect("/brand?error=unavailable");
  }
  if (!response.ok) {
    redirect(
      `/brand?error=${response.status === 409 ? "conflict" : response.status === 422 ? "invalid" : "unavailable"}`,
    );
  }
  redirect("/brand?updated=approved");
}

export async function approveWebsiteSpecification(
  formData: FormData,
): Promise<never> {
  let response: Response;
  try {
    response = await authenticatedApiRequest(
      "/website-specifications/approve",
      {
        run_id: field(formData, "run_id"),
        expected_version: Number(field(formData, "expected_version")),
      },
    );
  } catch {
    redirect("/website-specifications?error=unavailable");
  }
  if (!response.ok) {
    redirect(
      `/website-specifications?error=${response.status === 409 ? "conflict" : response.status === 422 ? "invalid" : "unavailable"}`,
    );
  }
  redirect("/website-specifications?updated=approved");
}

export async function startWebsiteProject(formData: FormData): Promise<never> {
  const baseProjectVersion = field(formData, "base_project_version");
  let response: Response;
  try {
    response = await authenticatedApiRequest("/website-projects/runs", {
      objective: field(formData, "objective"),
      operation: field(formData, "operation"),
      base_project_version: baseProjectVersion
        ? Number(baseProjectVersion)
        : null,
    });
  } catch {
    redirect("/website-projects?error=unavailable");
  }
  if (!response.ok) {
    redirect(
      `/website-projects?error=${response.status === 422 ? "invalid" : "unavailable"}`,
    );
  }
  redirect("/website-projects?updated=queued");
}

function taskError(response: Response): string {
  if (response.status === 404) return "not-found";
  if (response.status === 409) return "conflict";
  if (response.status === 422) return "invalid";
  return "unavailable";
}

async function taskMutation(
  path: string,
  body: Record<string, unknown>,
): Promise<Response> {
  try {
    return await authenticatedApiRequest(path, body);
  } catch {
    redirect("/tasks?error=unavailable");
  }
}

export async function createTask(formData: FormData): Promise<never> {
  const dueAt = field(formData, "due_at");
  const ownerValue = field(formData, "owner");
  const ownerType = ownerValue.startsWith("agent:") ? "agent" : ownerValue;
  const response = await taskMutation("/tasks", {
    title: field(formData, "title"),
    description: field(formData, "description"),
    goal_id: field(formData, "goal_id") || null,
    priority: Number(field(formData, "priority")),
    owner_type: ownerType,
    owner_agent_id:
      ownerType === "agent" ? ownerValue.slice("agent:".length) : null,
    due_at: dueAt ? new Date(dueAt).toISOString() : null,
    max_retries: Number(field(formData, "max_retries")),
  });
  if (!response.ok) redirect(`/tasks?error=${taskError(response)}`);
  const value: unknown = await response.json();
  if (
    typeof value !== "object" ||
    value === null ||
    typeof (value as { id?: unknown }).id !== "string"
  ) {
    redirect("/tasks?error=unavailable");
  }
  redirect(`/tasks?task=${(value as { id: string }).id}&updated=created`);
}

export async function addTaskDependency(
  taskId: string,
  formData: FormData,
): Promise<never> {
  const response = await taskMutation(
    `/tasks/${encodeURIComponent(taskId)}/dependencies`,
    { depends_on_task_id: field(formData, "depends_on_task_id") },
  );
  if (!response.ok) {
    redirect(
      `/tasks?task=${encodeURIComponent(taskId)}&error=${taskError(response)}`,
    );
  }
  redirect(`/tasks?task=${encodeURIComponent(taskId)}&updated=dependency`);
}

export async function transitionTask(
  taskId: string,
  formData: FormData,
): Promise<never> {
  const response = await taskMutation(
    `/tasks/${encodeURIComponent(taskId)}/status`,
    {
      status: field(formData, "status"),
      error: field(formData, "error") || null,
    },
  );
  if (!response.ok) {
    redirect(
      `/tasks?task=${encodeURIComponent(taskId)}&error=${taskError(response)}`,
    );
  }
  redirect(`/tasks?task=${encodeURIComponent(taskId)}&updated=transitioned`);
}

export async function retryTask(taskId: string): Promise<never> {
  const idempotencyKey = `ui:${taskId}:${crypto.randomUUID()}`;
  const response = await taskMutation(
    `/tasks/${encodeURIComponent(taskId)}/retry`,
    { idempotency_key: idempotencyKey },
  );
  if (!response.ok) {
    redirect(
      `/tasks?task=${encodeURIComponent(taskId)}&error=${taskError(response)}`,
    );
  }
  redirect(`/tasks?task=${encodeURIComponent(taskId)}&updated=retried`);
}

function workflowError(response: Response): string {
  if (response.status === 404) return "not-found";
  if (response.status === 409) return "conflict";
  if (response.status === 422) return "invalid";
  return "unavailable";
}

async function workflowMutation(
  path: string,
  body: Record<string, unknown> | undefined,
): Promise<Response> {
  try {
    return await authenticatedApiRequest(path, body);
  } catch {
    redirect("/workflows?error=unavailable");
  }
}

export async function startWorkflow(formData: FormData): Promise<never> {
  let input: Record<string, unknown>;
  try {
    const value: unknown = JSON.parse(field(formData, "input"));
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      redirect("/workflows?error=invalid");
    }
    input = value as Record<string, unknown>;
  } catch {
    redirect("/workflows?error=invalid");
  }
  const workflowId = field(formData, "workflow_id");
  const response = await workflowMutation(
    `/workflows/${encodeURIComponent(workflowId)}/runs`,
    { input, task_id: field(formData, "task_id") || null },
  );
  if (!response.ok) {
    redirect(`/workflows?error=${workflowError(response)}`);
  }
  const value: unknown = await response.json();
  if (
    typeof value !== "object" ||
    value === null ||
    typeof (value as { id?: unknown }).id !== "string"
  ) {
    redirect("/workflows?error=unavailable");
  }
  redirect(`/workflows?run=${(value as { id: string }).id}&updated=queued`);
}

export async function resumeWorkflow(
  runId: string,
  decision: "approved" | "rejected" | null,
): Promise<never> {
  const response = await workflowMutation(
    `/workflows/runs/${encodeURIComponent(runId)}/resume`,
    {
      idempotency_key: `ui:${runId}:${crypto.randomUUID()}`,
      decision,
      input: {},
    },
  );
  if (!response.ok) {
    redirect(
      `/workflows?run=${encodeURIComponent(runId)}&error=${workflowError(response)}`,
    );
  }
  redirect(`/workflows?run=${encodeURIComponent(runId)}&updated=resumed`);
}

export async function cancelWorkflow(runId: string): Promise<never> {
  const response = await workflowMutation(
    `/workflows/runs/${encodeURIComponent(runId)}/cancel`,
    undefined,
  );
  if (!response.ok) {
    redirect(
      `/workflows?run=${encodeURIComponent(runId)}&error=${workflowError(response)}`,
    );
  }
  redirect(`/workflows?run=${encodeURIComponent(runId)}&updated=cancelled`);
}

function governanceError(response: Response): string {
  if (response.status === 403) return "denied";
  if (response.status === 404) return "not-found";
  if (response.status === 409) return "conflict";
  if (response.status === 422) return "invalid";
  return "unavailable";
}

async function governanceMutation(
  path: string,
  body: Record<string, unknown>,
): Promise<Response> {
  try {
    return await authenticatedApiRequest(path, body);
  } catch {
    redirect("/governance?error=unavailable");
  }
}

export async function updateGovernanceSettings(
  formData: FormData,
): Promise<never> {
  const response = await governanceMutation("/governance/settings", {
    autonomy_level: field(formData, "autonomy_level"),
    daily_spend_limit_microusd: Number(
      field(formData, "daily_spend_limit_microusd"),
    ),
    per_action_spend_limit_microusd: Number(
      field(formData, "per_action_spend_limit_microusd"),
    ),
    revision: Number(field(formData, "revision")),
  });
  if (!response.ok) {
    redirect(`/governance?error=${governanceError(response)}`);
  }
  redirect("/governance?updated=settings");
}

export async function updateGovernanceKillSwitch(
  enabled: boolean,
  formData: FormData,
): Promise<never> {
  const response = await governanceMutation("/governance/kill-switch", {
    enabled,
    reason: field(formData, "reason") || null,
    revision: Number(field(formData, "revision")),
  });
  if (!response.ok) {
    redirect(`/governance?error=${governanceError(response)}`);
  }
  redirect(`/governance?updated=${enabled ? "killed" : "released"}`);
}

export async function updateGovernanceToolPermission(
  toolId: string,
  enabled: boolean,
  revision: number,
): Promise<never> {
  const response = await governanceMutation(
    `/governance/tools/${encodeURIComponent(toolId)}/permission`,
    { enabled, revision },
  );
  if (!response.ok) {
    redirect(`/governance?error=${governanceError(response)}`);
  }
  redirect("/governance?updated=tool");
}

export async function evaluateGovernanceAction(
  formData: FormData,
): Promise<never> {
  const actionType = field(formData, "action_type");
  const response = await governanceMutation("/governance/actions/evaluate", {
    action_type: actionType,
    tool_id: field(formData, "tool_id") || null,
    execution_mode: field(formData, "execution_mode"),
    data_classification: field(formData, "data_classification"),
    requested_spend_microusd: Number(
      field(formData, "requested_spend_microusd"),
    ),
    frequency_key: field(formData, "frequency_key") || null,
    target: field(formData, "target") || null,
    idempotency_key: `ui:governance:${crypto.randomUUID()}`,
  });
  if (!response.ok) {
    redirect(`/governance?error=${governanceError(response)}`);
  }
  const value: unknown = await response.json();
  if (
    typeof value !== "object" ||
    value === null ||
    typeof (value as { id?: unknown }).id !== "string"
  ) {
    redirect("/governance?error=unavailable");
  }
  redirect(
    `/governance?action=${(value as { id: string }).id}&updated=evaluated`,
  );
}

export async function decideGovernanceApproval(
  approvalId: string,
  decision: "approved" | "rejected",
  formData: FormData,
): Promise<never> {
  const response = await governanceMutation(
    `/governance/approvals/${encodeURIComponent(approvalId)}/decide`,
    {
      decision,
      reason: field(formData, "reason") || null,
      idempotency_key: `ui:approval:${approvalId}:${crypto.randomUUID()}`,
    },
  );
  if (!response.ok) {
    redirect(`/governance?error=${governanceError(response)}`);
  }
  redirect(`/governance?updated=${decision}`);
}

export async function authorizeGovernanceAction(
  actionId: string,
): Promise<never> {
  const response = await governanceMutation(
    `/governance/actions/${encodeURIComponent(actionId)}/authorize`,
    { idempotency_key: `ui:authorize:${actionId}:${crypto.randomUUID()}` },
  );
  if (!response.ok) {
    redirect(`/governance?error=${governanceError(response)}`);
  }
  redirect("/governance?updated=authorized");
}

export async function redriveEventDelivery(
  deliveryId: string,
  expectedRedriveCount: number,
): Promise<never> {
  let response: Response;
  try {
    response = await authenticatedApiRequest(
      `/events/deliveries/${encodeURIComponent(deliveryId)}/redrive`,
      { expected_redrive_count: expectedRedriveCount },
    );
  } catch {
    redirect("/events?error=unavailable");
  }
  if (!response.ok) redirect("/events?error=conflict");
  redirect("/events?updated=redriven");
}

function knowledgeError(response: Response): string {
  if (response.status === 404) return "not-found";
  if (response.status === 409) return "conflict";
  if ([413, 415, 422].includes(response.status)) return "invalid";
  return "unavailable";
}

export async function registerKnowledgeSource(
  formData: FormData,
): Promise<never> {
  let metadata: Record<string, unknown> = {};
  const metadataText = field(formData, "metadata").trim();
  if (metadataText) {
    try {
      const value: unknown = JSON.parse(metadataText);
      if (typeof value !== "object" || value === null || Array.isArray(value)) {
        redirect("/knowledge?error=invalid");
      }
      metadata = value as Record<string, unknown>;
    } catch {
      redirect("/knowledge?error=invalid");
    }
  }
  let response: Response;
  try {
    response = await authenticatedApiRequest("/knowledge/sources", {
      title: field(formData, "title"),
      source_type: field(formData, "source_type"),
      source_uri: field(formData, "source_uri") || null,
      metadata,
    });
  } catch {
    redirect("/knowledge?error=unavailable");
  }
  if (!response.ok) redirect(`/knowledge?error=${knowledgeError(response)}`);
  redirect("/knowledge?updated=source");
}

export async function uploadKnowledgeDocument(
  sourceId: string,
  formData: FormData,
): Promise<never> {
  const file = formData.get("file");
  if (!(file instanceof File) || !file.name || file.size === 0) {
    redirect("/knowledge?error=invalid");
  }
  const query = new URLSearchParams({
    filename: file.name,
    file_media_type: file.type || "application/octet-stream",
  });
  let response: Response;
  try {
    response = await authenticatedApiUpload(
      `/knowledge/sources/${encodeURIComponent(sourceId)}/documents?${query}`,
      await file.arrayBuffer(),
    );
  } catch {
    redirect("/knowledge?error=unavailable");
  }
  if (!response.ok) redirect(`/knowledge?error=${knowledgeError(response)}`);
  redirect("/knowledge?updated=indexed");
}

export async function invalidateKnowledgeSource(
  sourceId: string,
  expectedRevision: number,
  formData: FormData,
): Promise<never> {
  let response: Response;
  try {
    response = await authenticatedApiRequest(
      `/knowledge/sources/${encodeURIComponent(sourceId)}/invalidate`,
      {
        expected_revision: expectedRevision,
        reason: field(formData, "reason"),
      },
    );
  } catch {
    redirect("/knowledge?error=unavailable");
  }
  if (!response.ok) redirect(`/knowledge?error=${knowledgeError(response)}`);
  redirect("/knowledge?updated=invalidated");
}

export async function invalidateKnowledgeDocument(
  documentId: string,
  expectedRevision: number,
  formData: FormData,
): Promise<never> {
  let response: Response;
  try {
    response = await authenticatedApiRequest(
      `/knowledge/documents/${encodeURIComponent(documentId)}/invalidate`,
      {
        expected_revision: expectedRevision,
        reason: field(formData, "reason"),
      },
    );
  } catch {
    redirect("/knowledge?error=unavailable");
  }
  if (!response.ok) redirect(`/knowledge?error=${knowledgeError(response)}`);
  redirect("/knowledge?updated=invalidated");
}

function memoryError(response: Response): string {
  if (response.status === 404) return "not-found";
  if (response.status === 409) return "conflict";
  if (response.status === 422) return "invalid";
  return "unavailable";
}

async function memoryMutation(
  path: string,
  body: Record<string, unknown>,
): Promise<Response> {
  try {
    return await authenticatedApiRequest(path, body);
  } catch {
    redirect("/memory?error=unavailable");
  }
}

export async function updateMemoryPolicy(formData: FormData): Promise<never> {
  const response = await memoryMutation("/memory/policy", {
    automatic_accept_types: formData
      .getAll("automatic_accept_types")
      .filter((value): value is string => typeof value === "string"),
    minimum_confidence: Number(field(formData, "minimum_confidence")),
    expected_revision: Number(field(formData, "expected_revision")),
  });
  if (!response.ok) redirect(`/memory?error=${memoryError(response)}`);
  redirect("/memory?updated=policy");
}

export async function proposeMemory(formData: FormData): Promise<never> {
  let sourceMetadata: Record<string, unknown> = {};
  try {
    const raw = field(formData, "source_metadata").trim();
    if (raw) {
      const value: unknown = JSON.parse(raw);
      if (typeof value !== "object" || value === null || Array.isArray(value)) {
        redirect("/memory?error=invalid");
      }
      sourceMetadata = value as Record<string, unknown>;
    }
  } catch {
    redirect("/memory?error=invalid");
  }
  const expiry = field(formData, "expires_at");
  const response = await memoryMutation("/memory/proposals", {
    memory_type: field(formData, "memory_type"),
    epistemic_status: field(formData, "epistemic_status"),
    title: field(formData, "title"),
    content: field(formData, "content"),
    confidence: Number(field(formData, "confidence")),
    execution_type: field(formData, "execution_type") || null,
    execution_id: field(formData, "execution_id") || null,
    expires_at: expiry ? new Date(expiry).toISOString() : null,
    source_kind: field(formData, "source_kind"),
    source_id: field(formData, "source_id") || null,
    source_uri: field(formData, "source_uri") || null,
    source_label: field(formData, "source_label"),
    source_excerpt: field(formData, "source_excerpt") || null,
    source_metadata: sourceMetadata,
  });
  if (!response.ok) redirect(`/memory?error=${memoryError(response)}`);
  const value = (await response.json()) as { status?: string };
  redirect(
    `/memory?updated=${value.status === "pending" ? "proposed" : value.status}`,
  );
}

export async function decideMemoryProposal(
  proposalId: string,
  accept: boolean,
  formData: FormData,
): Promise<never> {
  const response = await memoryMutation(
    `/memory/proposals/${encodeURIComponent(proposalId)}/${accept ? "accept" : "reject"}`,
    {
      expected_revision: Number(field(formData, "expected_revision")),
      reason: field(formData, "reason"),
    },
  );
  if (!response.ok) redirect(`/memory?error=${memoryError(response)}`);
  const value = (await response.json()) as { status?: string };
  redirect(
    `/memory?updated=${value.status ?? (accept ? "accepted" : "rejected")}`,
  );
}

export async function invalidateMemory(
  memoryId: string,
  formData: FormData,
): Promise<never> {
  const response = await memoryMutation(
    `/memory/records/${encodeURIComponent(memoryId)}/invalidate`,
    {
      expected_revision: Number(field(formData, "expected_revision")),
      reason: field(formData, "reason"),
    },
  );
  if (!response.ok) redirect(`/memory?error=${memoryError(response)}`);
  redirect("/memory?updated=invalidated");
}

export async function logout(): Promise<never> {
  try {
    await authenticatedApiRequest("/auth/logout", undefined);
  } finally {
    await clearAuthCookies();
  }
  redirect("/login");
}

export async function revokeOtherSessions(): Promise<never> {
  let response: Response;
  try {
    response = await authenticatedApiRequest(
      "/auth/sessions/revoke-others",
      undefined,
    );
  } catch {
    redirect("/settings/security?error=unavailable");
  }
  if (!response.ok) redirect("/settings/security?error=session");
  redirect("/settings/security?updated=sessions");
}

export async function changePassword(formData: FormData): Promise<never> {
  const currentPassword = field(formData, "current_password");
  const newPassword = field(formData, "new_password");
  if (newPassword !== field(formData, "confirm_password")) {
    redirect("/settings/security?error=confirmation");
  }
  let response: Response;
  try {
    response = await authenticatedApiRequest("/auth/password", {
      current_password: currentPassword,
      new_password: newPassword,
    });
  } catch {
    redirect("/settings/security?error=unavailable");
  }
  if (!response.ok) {
    redirect(
      response.status === 401
        ? "/settings/security?error=current"
        : "/settings/security?error=password",
    );
  }
  if (!(await adoptAuthCookies(response))) {
    await clearAuthCookies();
    redirect("/login?error=unavailable");
  }
  redirect("/settings/security?updated=password");
}
