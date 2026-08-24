import "server-only";

import { cookies } from "next/headers";

export interface OwnerView {
  id: string;
  email: string;
}

export interface SessionView {
  id: string;
  created_at: string;
  last_seen_at: string;
  idle_expires_at: string;
  expires_at: string;
  user_agent: string | null;
  current: boolean;
}

export interface AuthView {
  owner: OwnerView;
  session: SessionView;
}

const sessionCookieName = "id";
const csrfCookieName = "csrf";

function apiUrl(path: string): string {
  const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  return `${base}${path}`;
}

export function publicOrigin(): string {
  return process.env.FOUNDORA_PUBLIC_ORIGIN ?? "http://localhost:3000";
}

function isSession(value: unknown): value is SessionView {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<SessionView>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.created_at === "string" &&
    typeof candidate.last_seen_at === "string" &&
    typeof candidate.idle_expires_at === "string" &&
    typeof candidate.expires_at === "string" &&
    (typeof candidate.user_agent === "string" ||
      candidate.user_agent === null) &&
    typeof candidate.current === "boolean"
  );
}

export function isAuthView(value: unknown): value is AuthView {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<AuthView>;
  return (
    typeof candidate.owner === "object" &&
    candidate.owner !== null &&
    typeof candidate.owner.id === "string" &&
    typeof candidate.owner.email === "string" &&
    isSession(candidate.session)
  );
}

async function authCookieHeader(): Promise<string | null> {
  const store = await cookies();
  const session = store.get(sessionCookieName)?.value;
  if (!session) return null;
  return `${sessionCookieName}=${session}`;
}

export async function getAuthSession(): Promise<AuthView | null> {
  const cookie = await authCookieHeader();
  if (!cookie) return null;
  try {
    const response = await fetch(apiUrl("/auth/session"), {
      cache: "no-store",
      headers: { Cookie: cookie },
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return null;
    const payload: unknown = await response.json();
    return isAuthView(payload) ? payload : null;
  } catch {
    return null;
  }
}

export async function getActiveSessions(): Promise<SessionView[] | null> {
  const cookie = await authCookieHeader();
  if (!cookie) return null;
  try {
    const response = await fetch(apiUrl("/auth/sessions"), {
      cache: "no-store",
      headers: { Cookie: cookie },
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return null;
    const payload: unknown = await response.json();
    return Array.isArray(payload) && payload.every(isSession) ? payload : null;
  } catch {
    return null;
  }
}

export async function authenticatedApiRequest(
  path: string,
  body: Record<string, unknown> | undefined,
): Promise<Response> {
  const store = await cookies();
  const session = store.get(sessionCookieName)?.value;
  const csrf = store.get(csrfCookieName)?.value;
  const headers = new Headers({
    Accept: "application/json",
    Origin: publicOrigin(),
    "X-CSRF-Token": csrf ?? "",
  });
  if (session) headers.set("Cookie", `${sessionCookieName}=${session}`);
  if (body) headers.set("Content-Type", "application/json");
  return fetch(apiUrl(path), {
    method: "POST",
    cache: "no-store",
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(5000),
  });
}

export async function authenticatedApiUpload(
  path: string,
  body: ArrayBuffer,
): Promise<Response> {
  const store = await cookies();
  const session = store.get(sessionCookieName)?.value;
  const csrf = store.get(csrfCookieName)?.value;
  const headers = new Headers({
    Accept: "application/json",
    "Content-Type": "application/octet-stream",
    Origin: publicOrigin(),
    "X-CSRF-Token": csrf ?? "",
  });
  if (session) headers.set("Cookie", `${sessionCookieName}=${session}`);
  return fetch(apiUrl(path), {
    method: "POST",
    cache: "no-store",
    headers,
    body,
    signal: AbortSignal.timeout(15000),
  });
}

export async function loginApiRequest(
  email: string,
  password: string,
): Promise<Response> {
  return fetch(apiUrl("/auth/login"), {
    method: "POST",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Origin: publicOrigin(),
    },
    body: JSON.stringify({ email, password }),
    signal: AbortSignal.timeout(5000),
  });
}

export async function adoptAuthCookies(response: Response): Promise<boolean> {
  const values = response.headers.getSetCookie();
  const session = readCookie(values, sessionCookieName);
  const csrf = readCookie(values, csrfCookieName);
  if (!session || !csrf) return false;
  const payload: unknown = await response.clone().json();
  if (!isAuthView(payload)) return false;
  const expires = new Date(payload.session.expires_at);
  if (Number.isNaN(expires.valueOf())) return false;
  const secure = publicOrigin().startsWith("https://");
  const store = await cookies();
  for (const [name, value] of [
    [sessionCookieName, session],
    [csrfCookieName, csrf],
  ] as const) {
    store.set(name, value, {
      expires,
      httpOnly: true,
      path: "/",
      sameSite: "strict",
      secure,
    });
  }
  return true;
}

function readCookie(values: string[], name: string): string | null {
  for (const value of values) {
    const pair = value.split(";", 1)[0];
    const separator = pair.indexOf("=");
    if (separator === -1) continue;
    if (pair.slice(0, separator) === name) return pair.slice(separator + 1);
  }
  return null;
}

export async function clearAuthCookies(): Promise<void> {
  const store = await cookies();
  store.delete(sessionCookieName);
  store.delete(csrfCookieName);
}
