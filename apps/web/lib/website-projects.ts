import "server-only";

import { cookies } from "next/headers";

export interface WebsiteProject {
  id: string;
  version: number;
  status: "active" | "superseded";
  operation: "generate" | "modify";
  source_agent_run_id: string;
  source_website_specification_id: string;
  source_website_specification_version: number;
  base_project_id: string | null;
  base_project_version: number | null;
  context_id: string;
  source_files: Array<Record<string, unknown>>;
  dependency_manifest: Record<string, unknown>;
  source_digest: string;
  build_digest: string;
  build_manifest: Array<Record<string, unknown>>;
  build_report: Record<string, unknown>;
  check_report: Record<string, unknown>;
  tool_audit: Array<Record<string, unknown>>;
  source_is_current: boolean;
  created_at: string;
  superseded_at: string | null;
}

export interface WebsiteProjectDashboard {
  business_id: string;
  current_specification: {
    id: string;
    version: number;
    approved_at: string;
  } | null;
  current_project: WebsiteProject | null;
  history: WebsiteProject[];
  recent_runs: Array<{
    id: string;
    status: string;
    error_type: string | null;
    error_message: string | null;
    created_at: string;
    completed_at: string | null;
  }>;
  next_operation: "generate" | "modify" | null;
  blocker: string | null;
}

export async function getWebsiteProjectDashboard(): Promise<WebsiteProjectDashboard | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}/website-projects`, {
      cache: "no-store",
      headers: { Cookie: `id=${session}` },
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    const value: unknown = await response.json();
    if (typeof value !== "object" || value === null) return null;
    const dashboard = value as Partial<WebsiteProjectDashboard>;
    if (
      typeof dashboard.business_id !== "string" ||
      !Array.isArray(dashboard.history) ||
      !Array.isArray(dashboard.recent_runs)
    )
      return null;
    return value as WebsiteProjectDashboard;
  } catch {
    return null;
  }
}
