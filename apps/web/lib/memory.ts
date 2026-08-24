import "server-only";

import { cookies } from "next/headers";

export const memoryTypes = [
  "working",
  "episodic",
  "semantic",
  "decision",
  "preference",
  "workflow",
  "evaluation",
] as const;
export type MemoryType = (typeof memoryTypes)[number];
export type EpistemicStatus =
  | "observation"
  | "assumption"
  | "fact"
  | "decision"
  | "preference"
  | "procedure"
  | "evaluation";

export interface MemoryProposal {
  id: string;
  memory_type: MemoryType;
  epistemic_status: EpistemicStatus;
  title: string;
  content: string;
  confidence: number;
  status: "pending" | "accepted" | "rejected" | "merged";
  acceptance_route: "founder" | "automatic";
  execution_type: string | null;
  execution_id: string | null;
  expires_at: string | null;
  source_kind: string;
  source_id: string | null;
  source_uri: string | null;
  source_label: string;
  source_excerpt: string | null;
  source_metadata: Record<string, unknown>;
  resolution_memory_id: string | null;
  decision_reason: string | null;
  revision: number;
  created_at: string;
  decided_at: string | null;
}

export interface MemoryRecord {
  id: string;
  memory_type: MemoryType;
  epistemic_status: EpistemicStatus;
  title: string;
  content: string;
  confidence: number;
  status: "active" | "expired" | "invalidated";
  accepted_via: "founder" | "automatic";
  execution_type: string | null;
  execution_id: string | null;
  expires_at: string | null;
  current_revision: number;
  created_at: string;
  updated_at: string;
  invalidated_at: string | null;
  invalidation_reason: string | null;
  revisions: Array<{
    revision: number;
    proposal_id: string;
    change_type: "accepted" | "merged";
    confidence: number;
    created_by: "founder" | "automatic";
    created_at: string;
  }>;
  provenance: Array<{
    revision: number;
    source_kind: string;
    source_id: string | null;
    source_uri: string | null;
    source_label: string;
    source_excerpt: string | null;
    source_metadata: Record<string, unknown>;
    created_at: string;
  }>;
}

export interface MemoryDashboard {
  business_id: string;
  memory_types: MemoryType[];
  epistemic_statuses_by_type: Record<MemoryType, EpistemicStatus[]>;
  policy: {
    automatic_accept_types: MemoryType[];
    minimum_confidence: number;
    revision: number;
    persisted: boolean;
  };
  proposals: MemoryProposal[];
  memories: MemoryRecord[];
}

export async function getMemoryDashboard(options?: {
  query?: string;
  memoryType?: string;
}): Promise<MemoryDashboard | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  const query = new URLSearchParams();
  if (options?.query) query.set("query", options.query);
  if (options?.memoryType) query.set("memory_types", options.memoryType);
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(
      `${base}/memory${query.size ? `?${query}` : ""}`,
      {
        cache: "no-store",
        headers: { Cookie: `id=${session}` },
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!response.ok) return null;
    const value: unknown = await response.json();
    if (typeof value !== "object" || value === null) return null;
    const dashboard = value as Partial<MemoryDashboard>;
    return typeof dashboard.business_id === "string" &&
      Array.isArray(dashboard.proposals) &&
      Array.isArray(dashboard.memories)
      ? (dashboard as MemoryDashboard)
      : null;
  } catch {
    return null;
  }
}
