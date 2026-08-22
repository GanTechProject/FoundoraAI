"use server";

import { redirect } from "next/navigation";

import {
  adoptAuthCookies,
  authenticatedApiRequest,
  clearAuthCookies,
  loginApiRequest,
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
    response = await authenticatedApiRequest("/ai/generate", {
      task_type: "gateway.acceptance",
      prompt: "Reply with exactly FOUNDORA_GATEWAY_OK and nothing else.",
      system_prompt: "Follow the requested output format exactly.",
      sensitivity: "standard",
      allow_fallback: true,
      max_output_tokens: 32,
      token_budget: 1024,
      cost_budget_microusd: 2000,
    });
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
  let response: Response;
  try {
    response = await authenticatedApiRequest(
      `/agents/${encodeURIComponent(agentId)}/runs`,
      { objective: field(formData, "objective") },
    );
  } catch {
    redirect("/agents?error=unavailable");
  }
  if (!response.ok) {
    redirect(
      `/agents?error=${response.status === 422 ? "invalid" : response.status === 404 ? "agent" : "unavailable"}`,
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
