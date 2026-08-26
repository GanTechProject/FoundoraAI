import { beforeEach, describe, expect, it, vi } from "vitest";

const { cookieStore } = vi.hoisted(() => ({
  cookieStore: {
    get: vi.fn(),
    set: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => cookieStore),
}));

import {
  adoptAuthCookies,
  authenticatedApiRequest,
  modelRequestTimeoutMs,
  normalMutationTimeoutMs,
} from "./auth";

function authPayload() {
  return {
    owner: { id: "owner-1", email: "owner@example.com" },
    session: {
      id: "session-1",
      created_at: "2026-08-26T00:00:00Z",
      last_seen_at: "2026-08-26T00:00:00Z",
      idle_expires_at: "2026-08-26T00:30:00Z",
      expires_at: "2026-08-26T08:00:00Z",
      user_agent: "test",
      current: true,
    },
  };
}

describe("authenticated API boundary", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    cookieStore.get.mockImplementation((name: string) =>
      name === "id"
        ? { value: "session-token" }
        : name === "csrf"
          ? { value: "csrf-token" }
          : undefined,
    );
    cookieStore.set.mockReset();
    delete process.env.API_MODEL_REQUEST_TIMEOUT_MS;
    process.env.API_INTERNAL_URL = "http://api.test";
    process.env.FOUNDORA_PUBLIC_ORIGIN = "http://foundora.test";
  });

  it("keeps ordinary mutations bounded to five seconds", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    await authenticatedApiRequest("/tasks", { title: "Review" });

    expect(timeout).toHaveBeenCalledWith(normalMutationTimeoutMs);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/tasks",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ title: "Review" }),
      }),
    );
    const request = fetchMock.mock.calls[0]?.[1];
    const headers = new Headers(request?.headers);
    expect(headers.get("Cookie")).toBe("id=session-token");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-token");
  });

  it("budgets model work for default retries and fallback", () => {
    expect(modelRequestTimeoutMs()).toBe(300_000);
    process.env.API_MODEL_REQUEST_TIMEOUT_MS = "420000";
    expect(modelRequestTimeoutMs()).toBe(420_000);
    process.env.API_MODEL_REQUEST_TIMEOUT_MS = "5000";
    expect(modelRequestTimeoutMs()).toBe(300_000);
  });

  it("adopts only a complete authenticated cookie pair", async () => {
    const headers = new Headers({ "Content-Type": "application/json" });
    headers.append("Set-Cookie", "id=session-token; HttpOnly; Path=/");
    headers.append("Set-Cookie", "csrf=csrf-token; HttpOnly; Path=/");
    const response = new Response(JSON.stringify(authPayload()), { headers });

    await expect(adoptAuthCookies(response)).resolves.toBe(true);

    expect(cookieStore.set).toHaveBeenCalledTimes(2);
    expect(cookieStore.set).toHaveBeenCalledWith(
      "id",
      "session-token",
      expect.objectContaining({ httpOnly: true, sameSite: "strict" }),
    );
    expect(cookieStore.set).toHaveBeenCalledWith(
      "csrf",
      "csrf-token",
      expect.objectContaining({ httpOnly: true, sameSite: "strict" }),
    );
  });
});
