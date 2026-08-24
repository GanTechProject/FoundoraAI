import "server-only";

import { cookies } from "next/headers";

export type WorkflowRunStatus =
  | "queued"
  | "running"
  | "waiting"
  | "waiting_approval"
  | "waiting_agent"
  | "completed"
  | "failed"
  | "cancelled";

export interface WorkflowDefinition {
  workflow_id: string;
  display_name: string;
  enabled: boolean;
  version_id: string;
  version: number;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  steps: Array<{
    key: string;
    type: "tool" | "agent" | "approval" | "wait";
    depends_on: string[];
    max_retries: number;
    condition: Record<string, unknown> | null;
    tool: string | null;
    agent_id: string | null;
    compensation: string | null;
  }>;
}

export interface WorkflowRun {
  id: string;
  business_id: string;
  workflow_id: string;
  workflow_version_id: string;
  workflow_version: number;
  task_id: string | null;
  status: WorkflowRunStatus;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  current_step_key: string | null;
  error_type: string | null;
  error_message: string | null;
  worker_recovery_count: number;
  created_at: string;
  queued_at: string;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  steps: Array<{
    id: string;
    key: string;
    sequence: number;
    type: "tool" | "agent" | "approval" | "wait";
    status: string;
    attempt_count: number;
    max_retries: number;
    agent_run_id: string | null;
    input: Record<string, unknown> | null;
    output: Record<string, unknown> | null;
    error_type: string | null;
    error_message: string | null;
    started_at: string | null;
    completed_at: string | null;
  }>;
  events: Array<{
    id: string;
    sequence: number;
    event_type: string;
    step_key: string | null;
    idempotency_key: string | null;
    details: Record<string, unknown>;
    created_at: string;
  }>;
}

export interface WorkflowDashboard {
  business_id: string;
  definitions: WorkflowDefinition[];
  runs: WorkflowRun[];
}

const statuses: WorkflowRunStatus[] = [
  "queued",
  "running",
  "waiting",
  "waiting_approval",
  "waiting_agent",
  "completed",
  "failed",
  "cancelled",
];

function isRun(value: unknown): value is WorkflowRun {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<WorkflowRun>;
  return (
    typeof item.id === "string" &&
    typeof item.workflow_id === "string" &&
    typeof item.workflow_version === "number" &&
    statuses.includes(item.status as WorkflowRunStatus) &&
    Array.isArray(item.steps) &&
    Array.isArray(item.events)
  );
}

function isDashboard(value: unknown): value is WorkflowDashboard {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<WorkflowDashboard>;
  return (
    typeof item.business_id === "string" &&
    Array.isArray(item.definitions) &&
    item.definitions.every(
      (definition) =>
        typeof definition === "object" &&
        definition !== null &&
        typeof (definition as WorkflowDefinition).workflow_id === "string" &&
        Array.isArray((definition as WorkflowDefinition).steps),
    ) &&
    Array.isArray(item.runs) &&
    item.runs.every(isRun)
  );
}

async function workflowFetch(path: string): Promise<unknown | null> {
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
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

export async function getWorkflowDashboard(): Promise<WorkflowDashboard | null> {
  const value = await workflowFetch("/workflows");
  return isDashboard(value) ? value : null;
}

export async function getWorkflowRun(
  runId: string,
): Promise<WorkflowRun | null> {
  if (!/^[0-9a-f-]{36}$/i.test(runId)) return null;
  const value = await workflowFetch(
    `/workflows/runs/${encodeURIComponent(runId)}`,
  );
  return isRun(value) ? value : null;
}
