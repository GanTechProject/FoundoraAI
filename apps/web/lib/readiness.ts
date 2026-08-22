export type ComponentStatus = "up" | "down";

export interface ReadinessPayload {
  status: "ready" | "not_ready";
  checks: Record<string, { status: ComponentStatus; detail?: string }>;
}

export interface ServiceView {
  name: string;
  status: ComponentStatus;
  detail: string;
}

export function isReadinessPayload(value: unknown): value is ReadinessPayload {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<ReadinessPayload>;
  if (candidate.status !== "ready" && candidate.status !== "not_ready")
    return false;
  if (typeof candidate.checks !== "object" || candidate.checks === null)
    return false;

  return Object.values(candidate.checks).every(
    (check) =>
      typeof check === "object" &&
      check !== null &&
      (check.status === "up" || check.status === "down"),
  );
}

export function toServiceViews(payload: ReadinessPayload): ServiceView[] {
  return Object.entries(payload.checks).map(([name, check]) => ({
    name,
    status: check.status,
    detail:
      check.detail ?? (check.status === "up" ? "Reachable" : "Unavailable"),
  }));
}
