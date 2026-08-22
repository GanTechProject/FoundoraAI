import "server-only";

import { cookies } from "next/headers";

export type AgentRunStatus =
  | "queued"
  | "running"
  | "waiting_tool"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export interface AgentDefinition {
  agent_id: string;
  display_name: string;
  enabled: boolean;
  version_id: string;
  version: number;
  role: string;
  purpose: string;
  responsibilities: string[];
  non_responsibilities: string[];
  allowed_task_types: string[];
  allowed_skills: string[];
  allowed_tools: string[];
  forbidden_actions: string[];
  model_policy: Record<string, unknown>;
  data_access_scope: Record<string, unknown>;
  risk_level: string;
  maximum_autonomy: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  evaluation_criteria: string[];
  escalation_criteria: string[];
}

export interface AgentUsageCall {
  operation_id: string;
  provider: string;
  model: string;
  status: "succeeded" | "failed";
  attempt_number: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_microusd: number;
  error_type: string | null;
  created_at: string;
}

export interface AgentRun {
  id: string;
  business_id: string;
  agent_id: string;
  agent_version_id: string;
  agent_version: number;
  status: AgentRunStatus;
  structured_input: Record<string, unknown>;
  structured_output: Record<string, unknown> | null;
  model_operation_id: string | null;
  error_type: string | null;
  error_message: string | null;
  created_at: string;
  queued_at: string;
  started_at: string | null;
  completed_at: string | null;
  cancellation_requested_at: string | null;
  cancelled_at: string | null;
  messages: Array<{
    sequence: number;
    role: "user" | "assistant" | "system";
    message_type: "input" | "output" | "error";
    content: Record<string, unknown>;
    created_at: string;
  }>;
  usage: {
    calls: number;
    total_tokens: number;
    estimated_cost_microusd: number;
    attempts: AgentUsageCall[];
  };
}

export interface AgentDashboard {
  business_id: string;
  definitions: AgentDefinition[];
  runs: AgentRun[];
}

const statuses: AgentRunStatus[] = [
  "queued",
  "running",
  "waiting_tool",
  "waiting_approval",
  "completed",
  "failed",
  "cancelled",
];

function stringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

function isDefinition(value: unknown): value is AgentDefinition {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<AgentDefinition>;
  return (
    typeof item.agent_id === "string" &&
    typeof item.display_name === "string" &&
    typeof item.enabled === "boolean" &&
    typeof item.version === "number" &&
    typeof item.role === "string" &&
    typeof item.purpose === "string" &&
    stringArray(item.responsibilities) &&
    stringArray(item.allowed_skills) &&
    stringArray(item.allowed_tools) &&
    stringArray(item.forbidden_actions) &&
    typeof item.model_policy === "object" &&
    item.model_policy !== null
  );
}

function isRun(value: unknown): value is AgentRun {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<AgentRun>;
  return (
    typeof item.id === "string" &&
    typeof item.business_id === "string" &&
    typeof item.agent_id === "string" &&
    typeof item.agent_version === "number" &&
    statuses.includes(item.status as AgentRunStatus) &&
    typeof item.structured_input === "object" &&
    item.structured_input !== null &&
    typeof item.created_at === "string" &&
    Array.isArray(item.messages) &&
    typeof item.usage === "object" &&
    item.usage !== null &&
    typeof item.usage.calls === "number" &&
    Array.isArray(item.usage.attempts)
  );
}

function isDashboard(value: unknown): value is AgentDashboard {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<AgentDashboard>;
  return (
    typeof item.business_id === "string" &&
    Array.isArray(item.definitions) &&
    item.definitions.every(isDefinition) &&
    Array.isArray(item.runs) &&
    item.runs.every(isRun)
  );
}

async function agentFetch(path: string): Promise<unknown | null> {
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

export async function getAgentDashboard(): Promise<AgentDashboard | null> {
  const value = await agentFetch("/agents");
  return isDashboard(value) ? value : null;
}

export async function getAgentRun(runId: string): Promise<AgentRun | null> {
  if (!/^[0-9a-f-]{36}$/i.test(runId)) return null;
  const value = await agentFetch(`/agents/runs/${encodeURIComponent(runId)}`);
  return isRun(value) ? value : null;
}
