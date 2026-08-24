import "server-only";

import { cookies } from "next/headers";

export type DeliveryStatus =
  "pending" | "retry_wait" | "processing" | "completed" | "dead_letter";

export interface EventDelivery {
  id: string;
  consumer_name: string;
  status: DeliveryStatus;
  attempt_count: number;
  max_attempts: number;
  redrive_count: number;
  available_at: string;
  claimed_at: string | null;
  completed_at: string | null;
  dead_lettered_at: string | null;
  last_error_type: string | null;
  last_error_message: string | null;
  handler_result: Record<string, unknown> | null;
}

export interface DomainEvent {
  id: string;
  event_type: string;
  schema_version: number;
  aggregate_type: string;
  aggregate_id: string;
  idempotency_key: string;
  correlation_id: string | null;
  causation_event_id: string | null;
  payload: Record<string, unknown>;
  occurred_at: string;
  deliveries: EventDelivery[];
}

export interface EventDashboard {
  business_id: string;
  contracts: Array<{
    event_type: string;
    schema_version: number;
    aggregate_type: string;
    description: string;
    consumer_names: string[];
  }>;
  events: DomainEvent[];
  total_events: number;
  limit: number;
  offset: number;
}

function isDashboard(value: unknown): value is EventDashboard {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<EventDashboard>;
  return (
    typeof item.business_id === "string" &&
    Array.isArray(item.contracts) &&
    Array.isArray(item.events) &&
    typeof item.total_events === "number" &&
    typeof item.limit === "number" &&
    typeof item.offset === "number"
  );
}

export async function getEventDashboard(
  deliveryStatus?: DeliveryStatus,
): Promise<EventDashboard | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  const query = deliveryStatus
    ? `?delivery_status=${encodeURIComponent(deliveryStatus)}`
    : "";
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}/events${query}`, {
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
