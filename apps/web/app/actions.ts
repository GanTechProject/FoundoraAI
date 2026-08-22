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
  body: Record<string, string | null> | undefined,
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
