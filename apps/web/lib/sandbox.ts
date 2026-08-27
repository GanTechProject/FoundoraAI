import "server-only";

import { cookies } from "next/headers";

export type SandboxExecutionStatus =
  | "requested"
  | "waiting_approval"
  | "queued"
  | "authorizing"
  | "running"
  | "cleaning"
  | "rejected"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "timed_out"
  | "resource_exhausted"
  | "infrastructure_failed"
  | "cleanup_failed";

export interface SandboxExecutionSummary {
  id: string;
  business_id: string;
  website_project_id: string;
  website_project_version: number;
  website_specification_id: string;
  website_specification_version: number;
  profile_id: string;
  profile_version: number;
  governance_action_id: string;
  governance_status: string;
  status: SandboxExecutionStatus;
  cleanup_status: "pending" | "verified" | "failed";
  final_labeled_resource_count: number | null;
  cancellation_requested_at: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface SandboxExecutionDetail extends SandboxExecutionSummary {
  harness_contract_version: number;
  source_digest: string;
  build_digest: string;
  source_archive_sha256: string;
  source_archive_size_bytes: number;
  routes: string[];
  request_digest: string;
  policy_version_id: string;
  governance_risk_class: string;
  governance_rationale: string;
  governance_authorized_at: string | null;
  approval: {
    id: string;
    status: string;
    prompt: string;
    decision_reason: string | null;
    requested_at: string;
    decided_at: string | null;
  } | null;
  worker_recovery_count: number;
  attempt_started_at: string | null;
  heartbeat_at: string | null;
  runtime_image_id: string | null;
  effective_limits: Record<string, unknown> | null;
  effective_limits_digest: string | null;
  termination_reason: string | null;
  exit_code: number | null;
  route_results: Array<Record<string, unknown>> | null;
  process_results: Record<string, unknown> | null;
  stdout_excerpt: string | null;
  stderr_excerpt: string | null;
  stdout_sha256: string | null;
  stderr_sha256: string | null;
  cleanup_attempts: number;
  cleanup_started_at: string | null;
  cleanup_finished_at: string | null;
  cleanup_receipt_digest: string | null;
}

export interface SandboxExecutionPage {
  business_id: string;
  executions: SandboxExecutionSummary[];
  total_executions: number;
  limit: number;
  offset: number;
}

function isSummary(value: unknown): value is SandboxExecutionSummary {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<SandboxExecutionSummary>;
  return (
    typeof item.id === "string" &&
    typeof item.business_id === "string" &&
    typeof item.website_project_id === "string" &&
    typeof item.website_project_version === "number" &&
    typeof item.governance_action_id === "string" &&
    typeof item.governance_status === "string" &&
    typeof item.status === "string" &&
    typeof item.cleanup_status === "string" &&
    typeof item.created_at === "string" &&
    typeof item.updated_at === "string"
  );
}

function isPage(value: unknown): value is SandboxExecutionPage {
  if (typeof value !== "object" || value === null) return false;
  const page = value as Partial<SandboxExecutionPage>;
  return (
    typeof page.business_id === "string" &&
    Array.isArray(page.executions) &&
    page.executions.every(isSummary) &&
    typeof page.total_executions === "number" &&
    typeof page.limit === "number" &&
    typeof page.offset === "number"
  );
}

function isDetail(value: unknown): value is SandboxExecutionDetail {
  if (!isSummary(value)) return false;
  const detail = value as Partial<SandboxExecutionDetail>;
  return (
    typeof detail.request_digest === "string" &&
    typeof detail.source_digest === "string" &&
    typeof detail.build_digest === "string" &&
    Array.isArray(detail.routes) &&
    typeof detail.governance_rationale === "string" &&
    typeof detail.worker_recovery_count === "number" &&
    typeof detail.cleanup_attempts === "number"
  );
}

async function getSandbox(path: string): Promise<unknown | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}${path}`, {
      cache: "no-store",
      headers: { Cookie: `id=${session}` },
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

export async function getSandboxExecutions(): Promise<SandboxExecutionPage | null> {
  const value = await getSandbox("/sandbox/executions?limit=50&offset=0");
  return isPage(value) ? value : null;
}

export async function getSandboxExecution(
  executionId: string,
): Promise<SandboxExecutionDetail | null> {
  const value = await getSandbox(
    `/sandbox/executions/${encodeURIComponent(executionId)}`,
  );
  return isDetail(value) ? value : null;
}
