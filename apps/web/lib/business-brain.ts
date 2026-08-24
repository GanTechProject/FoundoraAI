import "server-only";

import { cookies } from "next/headers";

export const contextSourceTypes = [
  "business_profile",
  "approved_profile",
  "approved_goals",
  "products_services",
  "brand",
  "operating_context",
  "operational_goals",
  "current_tasks",
  "knowledge",
] as const;

export type ContextSourceType = (typeof contextSourceTypes)[number];
export type SourceValidity = "current" | "stale" | "invalidated";
export type SelectionStatus = "included" | "excluded";

export interface ContextSource {
  source_type: ContextSourceType;
  source_reference: string;
  source_version: string;
  authority: string;
  label: string;
  updated_at: string;
  validity: SourceValidity;
  selection_status: SelectionStatus;
  exclusion_reason:
    "not_selected" | "stale" | "invalidated" | "token_budget" | null;
  estimated_tokens: number;
  content_sha256: string;
  content: Record<string, unknown> | null;
}

export interface BusinessContext {
  context_id: string;
  business_id: string;
  purpose: string;
  generated_at: string;
  token_budget: number;
  estimated_tokens: number;
  budget_remaining: number;
  selected_source_types: ContextSourceType[];
  sources: ContextSource[];
  unavailable_sources: Record<string, string>;
  context: string;
  context_sha256: string;
}

function isSource(value: unknown): value is ContextSource {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<ContextSource>;
  return (
    contextSourceTypes.includes(item.source_type as ContextSourceType) &&
    typeof item.source_reference === "string" &&
    typeof item.source_version === "string" &&
    typeof item.authority === "string" &&
    typeof item.label === "string" &&
    typeof item.updated_at === "string" &&
    ["current", "stale", "invalidated"].includes(item.validity ?? "") &&
    ["included", "excluded"].includes(item.selection_status ?? "") &&
    typeof item.estimated_tokens === "number" &&
    typeof item.content_sha256 === "string"
  );
}

function isBusinessContext(value: unknown): value is BusinessContext {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<BusinessContext>;
  return (
    typeof item.context_id === "string" &&
    typeof item.business_id === "string" &&
    typeof item.purpose === "string" &&
    typeof item.generated_at === "string" &&
    typeof item.token_budget === "number" &&
    typeof item.estimated_tokens === "number" &&
    typeof item.budget_remaining === "number" &&
    Array.isArray(item.selected_source_types) &&
    item.selected_source_types.every((source) =>
      contextSourceTypes.includes(source),
    ) &&
    Array.isArray(item.sources) &&
    item.sources.every(isSource) &&
    typeof item.unavailable_sources === "object" &&
    item.unavailable_sources !== null &&
    typeof item.context === "string" &&
    typeof item.context_sha256 === "string"
  );
}

export async function getBusinessContext(options: {
  purpose: string;
  tokenBudget: number;
  sourceTypes: ContextSourceType[];
  knowledgeQuery?: string;
}): Promise<BusinessContext | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  const query = new URLSearchParams({
    purpose: options.purpose,
    token_budget: String(options.tokenBudget),
    sources: options.sourceTypes.join(","),
  });
  if (options.knowledgeQuery)
    query.set("knowledge_query", options.knowledgeQuery);
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}/brain/context?${query}`, {
      cache: "no-store",
      headers: { Cookie: `id=${session}` },
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    const value: unknown = await response.json();
    return isBusinessContext(value) ? value : null;
  } catch {
    return null;
  }
}
