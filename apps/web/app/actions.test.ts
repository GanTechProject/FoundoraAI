import { beforeEach, describe, expect, it, vi } from "vitest";

class RedirectError extends Error {
  constructor(readonly location: string) {
    super(`redirect:${location}`);
  }
}

const auth = vi.hoisted(() => ({
  request: vi.fn(),
  upload: vi.fn(),
  adopt: vi.fn(),
  clear: vi.fn(),
  login: vi.fn(),
  modelTimeout: vi.fn(() => 300_000),
}));

vi.mock("next/navigation", () => ({
  redirect: (location: string) => {
    throw new RedirectError(location);
  },
}));
vi.mock("../lib/auth", () => ({
  authenticatedApiRequest: auth.request,
  authenticatedApiUpload: auth.upload,
  adoptAuthCookies: auth.adopt,
  clearAuthCookies: auth.clear,
  loginApiRequest: auth.login,
  modelRequestTimeoutMs: auth.modelTimeout,
}));

import {
  approveStrategy,
  decideGovernanceApproval,
  runModelGatewayCheck,
  startWebsiteProject,
  validateModelProvider,
} from "./actions";

async function expectRedirect(promise: Promise<never>, location: string) {
  await expect(promise).rejects.toMatchObject({ location });
}

describe("server action contracts", () => {
  beforeEach(() => {
    auth.request.mockReset();
    auth.modelTimeout.mockClear();
  });

  it("uses the long provider budget for validation and generation", async () => {
    auth.request.mockResolvedValue(new Response(null, { status: 200 }));
    const provider = new FormData();
    provider.set("provider", "openai");

    await expectRedirect(
      validateModelProvider(provider),
      "/settings/ai?updated=validated",
    );
    expect(auth.request).toHaveBeenLastCalledWith(
      "/ai/providers/openai/validate",
      {},
      { timeoutMs: 300_000 },
    );

    await expectRedirect(
      runModelGatewayCheck(),
      "/settings/ai?updated=generated",
    );
    expect(auth.request).toHaveBeenLastCalledWith(
      "/ai/generate",
      expect.objectContaining({
        task_type: "gateway.acceptance",
        allow_fallback: true,
      }),
      { timeoutMs: 300_000 },
    );
  });

  it("maps stale strategy approval to a conflict", async () => {
    auth.request.mockResolvedValue(new Response(null, { status: 409 }));
    const form = new FormData();
    form.set("run_id", "run-1");
    form.set("expected_version", "2");

    await expectRedirect(approveStrategy(form), "/strategy?error=conflict");
    expect(auth.request).toHaveBeenCalledWith("/strategy/approve", {
      run_id: "run-1",
      expected_version: 2,
    });
  });

  it("preserves the Phase 21 modification base", async () => {
    auth.request.mockResolvedValue(new Response(null, { status: 202 }));
    const form = new FormData();
    form.set("objective", "Update the approved site");
    form.set("operation", "modify");
    form.set("base_project_version", "4");

    await expectRedirect(
      startWebsiteProject(form),
      "/website-projects?updated=queued",
    );
    expect(auth.request).toHaveBeenCalledWith("/website-projects/runs", {
      objective: "Update the approved site",
      operation: "modify",
      base_project_version: 4,
    });
  });

  it("submits explicit governance approval decisions", async () => {
    auth.request.mockResolvedValue(new Response(null, { status: 200 }));
    const form = new FormData();
    form.set("reason", "Reviewed against the active policy");

    await expectRedirect(
      decideGovernanceApproval("approval/1", "approved", form),
      "/governance?updated=approved",
    );
    expect(auth.request).toHaveBeenCalledWith(
      "/governance/approvals/approval%2F1/decide",
      expect.objectContaining({
        decision: "approved",
        reason: "Reviewed against the active policy",
        idempotency_key: expect.stringMatching(/^ui:approval:approval\/1:/),
      }),
    );
  });
});
