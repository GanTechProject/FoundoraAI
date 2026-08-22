import "server-only";

import { cookies } from "next/headers";

export type BusinessStatus = "planning" | "active" | "paused";
export type GoalStatus = "active" | "completed" | "cancelled";

export interface BusinessView {
  id: string;
  name: string;
  summary: string | null;
  status: BusinessStatus;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  selected: boolean;
}

export interface BusinessCollectionView {
  businesses: BusinessView[];
  selected_business_id: string | null;
}

export interface PreferenceView {
  timezone: string;
  currency: string;
  locale: string;
  updated_at: string;
}

export interface GoalView {
  id: string;
  title: string;
  details: string | null;
  target_date: string | null;
  status: GoalStatus;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceView {
  business: BusinessView;
  preferences: PreferenceView;
  goals: GoalView[];
}

const sessionCookieName = "id";

function apiUrl(path: string): string {
  const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  return `${base}${path}`;
}

function isBusiness(value: unknown): value is BusinessView {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<BusinessView>;
  return (
    typeof item.id === "string" &&
    typeof item.name === "string" &&
    (typeof item.summary === "string" || item.summary === null) &&
    ["planning", "active", "paused"].includes(item.status ?? "") &&
    typeof item.created_at === "string" &&
    typeof item.updated_at === "string" &&
    (typeof item.archived_at === "string" || item.archived_at === null) &&
    typeof item.selected === "boolean"
  );
}

function isPreference(value: unknown): value is PreferenceView {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<PreferenceView>;
  return (
    typeof item.timezone === "string" &&
    typeof item.currency === "string" &&
    typeof item.locale === "string" &&
    typeof item.updated_at === "string"
  );
}

function isGoal(value: unknown): value is GoalView {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<GoalView>;
  return (
    typeof item.id === "string" &&
    typeof item.title === "string" &&
    (typeof item.details === "string" || item.details === null) &&
    (typeof item.target_date === "string" || item.target_date === null) &&
    ["active", "completed", "cancelled"].includes(item.status ?? "") &&
    typeof item.created_at === "string" &&
    typeof item.updated_at === "string"
  );
}

async function apiGet(path: string): Promise<unknown | null> {
  const store = await cookies();
  const session = store.get(sessionCookieName)?.value;
  if (!session) return null;
  try {
    const response = await fetch(apiUrl(path), {
      cache: "no-store",
      headers: { Cookie: `${sessionCookieName}=${session}` },
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return null;
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
}

export async function getBusinesses(): Promise<BusinessCollectionView | null> {
  const value = await apiGet("/businesses");
  if (typeof value !== "object" || value === null) return null;
  const collection = value as Partial<BusinessCollectionView>;
  if (
    !Array.isArray(collection.businesses) ||
    !collection.businesses.every(isBusiness) ||
    !(
      typeof collection.selected_business_id === "string" ||
      collection.selected_business_id === null
    )
  ) {
    return null;
  }
  return collection as BusinessCollectionView;
}

export async function getWorkspace(): Promise<WorkspaceView | null> {
  const value = await apiGet("/workspace");
  if (typeof value !== "object" || value === null) return null;
  const workspace = value as Partial<WorkspaceView>;
  if (
    !isBusiness(workspace.business) ||
    !isPreference(workspace.preferences) ||
    !Array.isArray(workspace.goals) ||
    !workspace.goals.every(isGoal)
  ) {
    return null;
  }
  return workspace as WorkspaceView;
}
