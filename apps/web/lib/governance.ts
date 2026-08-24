import "server-only";

import { cookies } from "next/headers";

export type RiskClass = "R0" | "R1" | "R2" | "R3" | "R4" | "R5";
export type AutonomyLevel =
  "OFF" | "RECOMMEND" | "ASSISTED" | "AUTONOMOUS_LOW_RISK";

export interface GovernanceApproval {
  id: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  prompt: string;
  decision_reason: string | null;
  requested_at: string;
  decided_at: string | null;
}

export interface GovernanceAction {
  id: string;
  action_type: string;
  actor_type: "owner" | "agent" | "workflow" | "system";
  actor_id: string | null;
  tool_id: string | null;
  risk_class: RiskClass;
  execution_mode: "manual" | "autonomous";
  data_classification: "public" | "internal" | "confidential" | "restricted";
  requested_spend_microusd: number;
  target: string | null;
  status:
    | "approval_required"
    | "approved"
    | "rejected"
    | "authorized"
    | "denied"
    | "blocked";
  rationale: string;
  created_at: string;
  authorized_at: string | null;
  approval: GovernanceApproval | null;
}

export interface GovernanceDashboard {
  business_id: string;
  policy: {
    policy_id: string;
    display_name: string;
    version_id: string;
    version: number;
    description: string;
    rules: Record<string, unknown>;
  };
  controls: {
    kill_switch_enabled: boolean;
    reason: string | null;
    revision: number;
    updated_at: string;
  };
  settings: {
    autonomy_level: AutonomyLevel;
    daily_spend_limit_microusd: number;
    per_action_spend_limit_microusd: number;
    authorized_spend_today_microusd: number;
    revision: number;
    updated_at: string;
  };
  action_catalog: Array<{
    action_type: string;
    display_name: string;
    risk_class: RiskClass;
    description: string;
  }>;
  tool_permissions: Array<{
    tool_id: string;
    display_name: string;
    risk_class: RiskClass;
    internal: boolean;
    enabled: boolean;
    revision: number;
    updated_at: string;
  }>;
  actions: GovernanceAction[];
  audit_events: Array<{
    id: string;
    action_id: string | null;
    approval_request_id: string | null;
    event_type: string;
    details: Record<string, unknown>;
    created_at: string;
  }>;
}

function isDashboard(value: unknown): value is GovernanceDashboard {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<GovernanceDashboard>;
  return (
    typeof item.business_id === "string" &&
    typeof item.policy === "object" &&
    item.policy !== null &&
    typeof item.controls === "object" &&
    item.controls !== null &&
    typeof item.settings === "object" &&
    item.settings !== null &&
    Array.isArray(item.action_catalog) &&
    Array.isArray(item.tool_permissions) &&
    Array.isArray(item.actions) &&
    Array.isArray(item.audit_events)
  );
}

export async function getGovernanceDashboard(): Promise<GovernanceDashboard | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}/governance`, {
      cache: "no-store",
      headers: { Cookie: `id=${session}` },
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    const value: unknown = await response.json();
    return isDashboard(value) ? value : null;
  } catch {
    return null;
  }
}
