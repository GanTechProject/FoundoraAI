import "server-only";

import { cookies } from "next/headers";

export type OnboardingStatus = "draft" | "review" | "approved";
export type BusinessType = "idea" | "existing";

export interface OnboardingDraftView {
  status: OnboardingStatus;
  current_step: number;
  revision: number;
  business_type: BusinessType | null;
  business_name: string | null;
  industry: string | null;
  geography: string | null;
  problem: string | null;
  target_audience: string | null;
  offer: string | null;
  goals: string[];
  existing_assets: string[];
  constraints: string[];
  budget: string | null;
  brand_preferences: string | null;
  connected_services: string[];
  updated_at: string | null;
  submitted_at: string | null;
}

export interface ApprovedProfileView {
  version: number;
  business_type: BusinessType;
  business_name: string;
  industry: string;
  geography: string;
  problem: string;
  target_audience: string;
  offer: string;
  goals: string[];
  existing_assets: string[];
  constraints: string[];
  budget: string;
  brand_preferences: string;
  connected_services: string[];
  approved_at: string;
}

export interface OnboardingView {
  business_id: string;
  draft: OnboardingDraftView;
  approved_profile: ApprovedProfileView | null;
}

const statuses: OnboardingStatus[] = ["draft", "review", "approved"];
const businessTypes: BusinessType[] = ["idea", "existing"];

function nullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function strings(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

function isDraft(value: unknown): value is OnboardingDraftView {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<OnboardingDraftView>;
  return (
    statuses.includes(item.status as OnboardingStatus) &&
    typeof item.current_step === "number" &&
    typeof item.revision === "number" &&
    (item.business_type === null ||
      businessTypes.includes(item.business_type as BusinessType)) &&
    nullableString(item.business_name) &&
    nullableString(item.industry) &&
    nullableString(item.geography) &&
    nullableString(item.problem) &&
    nullableString(item.target_audience) &&
    nullableString(item.offer) &&
    strings(item.goals) &&
    strings(item.existing_assets) &&
    strings(item.constraints) &&
    nullableString(item.budget) &&
    nullableString(item.brand_preferences) &&
    strings(item.connected_services) &&
    nullableString(item.updated_at) &&
    nullableString(item.submitted_at)
  );
}

function isApproved(value: unknown): value is ApprovedProfileView {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<ApprovedProfileView>;
  return (
    typeof item.version === "number" &&
    businessTypes.includes(item.business_type as BusinessType) &&
    typeof item.business_name === "string" &&
    typeof item.industry === "string" &&
    typeof item.geography === "string" &&
    typeof item.problem === "string" &&
    typeof item.target_audience === "string" &&
    typeof item.offer === "string" &&
    strings(item.goals) &&
    strings(item.existing_assets) &&
    strings(item.constraints) &&
    typeof item.budget === "string" &&
    typeof item.brand_preferences === "string" &&
    strings(item.connected_services) &&
    typeof item.approved_at === "string"
  );
}

export async function getOnboarding(): Promise<OnboardingView | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}/onboarding`, {
      cache: "no-store",
      headers: { Cookie: `id=${session}` },
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return null;
    const value: unknown = await response.json();
    if (typeof value !== "object" || value === null) return null;
    const item = value as Partial<OnboardingView>;
    if (
      typeof item.business_id !== "string" ||
      !isDraft(item.draft) ||
      !(item.approved_profile === null || isApproved(item.approved_profile))
    ) {
      return null;
    }
    return item as OnboardingView;
  } catch {
    return null;
  }
}
