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
  redirect("/settings/security");
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
