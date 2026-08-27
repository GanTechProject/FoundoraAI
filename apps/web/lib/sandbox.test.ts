import { beforeEach, describe, expect, it, vi } from "vitest";

const { cookieStore } = vi.hoisted(() => ({
  cookieStore: { get: vi.fn() },
}));

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => cookieStore),
}));

import { getSandboxExecution, getSandboxExecutions } from "./sandbox";

function summary() {
  return {
    id: "execution-1",
    business_id: "business-1",
    website_project_id: "project-1",
    website_project_version: 1,
    website_specification_id: "specification-1",
    website_specification_version: 1,
    profile_id: "static-website",
    profile_version: 1,
    governance_action_id: "action-1",
    governance_status: "approved",
    status: "waiting_approval",
    cleanup_status: "pending",
    final_labeled_resource_count: null,
    cancellation_requested_at: null,
    created_at: "2026-08-27T00:00:00Z",
    started_at: null,
    finished_at: null,
    updated_at: "2026-08-27T00:00:00Z",
  };
}

describe("sandbox server data boundary", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    cookieStore.get.mockReturnValue({ value: "session-token" });
    process.env.API_INTERNAL_URL = "http://api.test";
  });

  it("uses the session cookie, no-store, and a bounded timeout for history", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          business_id: "business-1",
          executions: [summary()],
          total_executions: 1,
          limit: 50,
          offset: 0,
        }),
        { status: 200 },
      ),
    );

    await expect(getSandboxExecutions()).resolves.toMatchObject({
      total_executions: 1,
    });
    expect(timeout).toHaveBeenCalledWith(5000);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/sandbox/executions?limit=50&offset=0",
      expect.objectContaining({
        cache: "no-store",
        headers: { Cookie: "id=session-token" },
      }),
    );
  });

  it("keeps untrusted runner excerpts as plain data", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          ...summary(),
          harness_contract_version: 1,
          source_digest: "1".repeat(64),
          build_digest: "2".repeat(64),
          source_archive_sha256: "3".repeat(64),
          source_archive_size_bytes: 100,
          routes: ["/"],
          request_digest: "4".repeat(64),
          policy_version_id: "policy-1",
          governance_risk_class: "R2",
          governance_rationale: "Approved",
          governance_authorized_at: null,
          approval: null,
          worker_recovery_count: 0,
          attempt_started_at: null,
          heartbeat_at: null,
          runtime_image_id: null,
          effective_limits: null,
          effective_limits_digest: null,
          termination_reason: null,
          exit_code: null,
          route_results: null,
          process_results: null,
          stdout_excerpt: "<img src=x onerror=alert(1)>",
          stderr_excerpt: null,
          stdout_sha256: null,
          stderr_sha256: null,
          cleanup_attempts: 0,
          cleanup_started_at: null,
          cleanup_finished_at: null,
          cleanup_receipt_digest: null,
        }),
        { status: 200 },
      ),
    );

    await expect(getSandboxExecution("execution/1")).resolves.toMatchObject({
      stdout_excerpt: "<img src=x onerror=alert(1)>",
    });
  });
});
