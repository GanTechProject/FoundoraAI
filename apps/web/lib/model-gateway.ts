import "server-only";

import { cookies } from "next/headers";

export type ProviderName = "openai" | "gemini" | "anthropic";

export interface ProviderStatus {
  name: ProviderName;
  configured: boolean;
  model: string;
  validation_status: "never" | "valid" | "invalid";
  validated_at: string | null;
  validation_error_type: string | null;
}

export interface GatewayModel {
  provider: ProviderName;
  model: string;
  input_microusd_per_token: string;
  output_microusd_per_token: string;
  supports_streaming: boolean;
  supports_structured_output: boolean;
}

export interface GatewayCall {
  operation_id: string;
  task_type: string;
  sensitivity: "standard" | "sensitive";
  provider: ProviderName;
  model: string;
  status: "succeeded" | "failed";
  attempt_number: number;
  retry_number: number;
  fallback_from: ProviderName | null;
  streamed: boolean;
  structured: boolean;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_microusd: number;
  latency_ms: number;
  error_type: string | null;
  created_at: string;
}

export interface GatewayDashboard {
  business_id: string;
  providers: ProviderStatus[];
  models: GatewayModel[];
  primary_provider: ProviderName;
  fallback_providers: ProviderName[];
  task_routes: Record<string, { provider: string; model: string }>;
  default_max_output_tokens: number;
  default_token_budget: number;
  default_cost_budget_microusd: number;
  usage: {
    calls: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_cost_microusd: number;
  };
  recent_calls: GatewayCall[];
}

const providerNames: ProviderName[] = ["openai", "gemini", "anthropic"];

function isDashboard(value: unknown): value is GatewayDashboard {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<GatewayDashboard>;
  return (
    typeof item.business_id === "string" &&
    providerNames.includes(item.primary_provider as ProviderName) &&
    Array.isArray(item.fallback_providers) &&
    Array.isArray(item.providers) &&
    item.providers.every(
      (provider) =>
        providerNames.includes(provider.name) &&
        typeof provider.configured === "boolean" &&
        typeof provider.model === "string",
    ) &&
    Array.isArray(item.models) &&
    Array.isArray(item.recent_calls) &&
    typeof item.usage === "object" &&
    item.usage !== null &&
    typeof item.usage.calls === "number"
  );
}

export async function getModelGateway(): Promise<GatewayDashboard | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}/ai`, {
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
