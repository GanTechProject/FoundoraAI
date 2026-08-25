import "server-only";

import { cookies } from "next/headers";

export interface ProductOfferVersion {
  id: string;
  business_id: string;
  version: number;
  status: "active" | "superseded";
  source_agent_run_id: string;
  source_strategy_version: number;
  context_id: string;
  portfolio: Record<string, unknown>;
  evidence_refs: Record<string, unknown>;
  approved_by_owner_id: string;
  approved_at: string;
  superseded_at: string | null;
}

export interface ProductOfferDashboard {
  business_id: string;
  current_version: number;
  current: ProductOfferVersion | null;
  versions: ProductOfferVersion[];
  candidate_runs: Array<{
    run_id: string;
    context_id: string;
    portfolio_name: string;
    source_strategy_version: number;
    completed_at: string;
  }>;
}

export async function getProductOfferDashboard(): Promise<ProductOfferDashboard | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}/products-offers`, {
      cache: "no-store",
      headers: { Cookie: `id=${session}` },
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    const value: unknown = await response.json();
    if (typeof value !== "object" || value === null) return null;
    const item = value as Partial<ProductOfferDashboard>;
    if (
      typeof item.business_id !== "string" ||
      typeof item.current_version !== "number" ||
      !Array.isArray(item.versions) ||
      !Array.isArray(item.candidate_runs)
    )
      return null;
    return value as ProductOfferDashboard;
  } catch {
    return null;
  }
}
