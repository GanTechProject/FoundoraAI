import "server-only";

import { cookies } from "next/headers";

export interface StrategyDashboard {
  business_id: string;
  current_version: number;
  approved: {
    business_id: string;
    version: number;
    source_agent_run_id: string;
    context_id: string;
    strategy: Record<string, unknown>;
    evidence_refs: Record<string, unknown>;
    approved_by_owner_id: string;
    approved_at: string;
  } | null;
  candidate_runs: Array<{
    run_id: string;
    context_id: string;
    strategy_title: string;
    completed_at: string;
  }>;
}

export async function getStrategyDashboard(): Promise<StrategyDashboard | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}/strategy`, {
      cache: "no-store",
      headers: { Cookie: `id=${session}` },
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    const value: unknown = await response.json();
    if (typeof value !== "object" || value === null) return null;
    const item = value as Partial<StrategyDashboard>;
    if (
      typeof item.business_id !== "string" ||
      typeof item.current_version !== "number" ||
      !Array.isArray(item.candidate_runs)
    )
      return null;
    return value as StrategyDashboard;
  } catch {
    return null;
  }
}
