import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import {
  type ApprovedProfileView,
  getOnboarding,
  type OnboardingDraftView,
} from "../../lib/onboarding";
import {
  approveOnboarding,
  logout,
  reopenOnboarding,
  saveOnboardingBrandServices,
  saveOnboardingExecution,
  saveOnboardingFoundation,
  saveOnboardingMarket,
  submitOnboarding,
} from "../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  conflict:
    "This draft changed or is no longer editable. The latest saved version is shown.",
  incomplete:
    "Complete every required field and include at least one goal before review.",
  unavailable: "The onboarding service is temporarily unavailable.",
};

const updates: Record<string, string> = {
  approved:
    "Founder approval recorded. This version is now the approved business profile.",
  reopened:
    "Draft reopened. The last approved profile remains authoritative until you approve a revision.",
  saved: "Draft saved. You can leave and resume at any time.",
  submitted:
    "Draft frozen for review. No field becomes approved fact until you explicitly approve it.",
};

const steps = [
  "Foundation",
  "Market",
  "Execution",
  "Brand & services",
  "Review",
];

function lineValues(values: string[]): string {
  return values.join("\n");
}

function displayed(values: string[]): string {
  return values.length ? values.join(" · ") : "None declared";
}

function ReviewFields({
  profile,
}: {
  profile: OnboardingDraftView | ApprovedProfileView;
}) {
  return (
    <dl className="profile-review">
      <div>
        <dt>Business basis</dt>
        <dd>
          {profile.business_type === "existing"
            ? "Existing business"
            : "Business idea"}
        </dd>
      </div>
      <div>
        <dt>Name</dt>
        <dd>{profile.business_name ?? "Not entered"}</dd>
      </div>
      <div>
        <dt>Industry</dt>
        <dd>{profile.industry ?? "Not entered"}</dd>
      </div>
      <div>
        <dt>Geography</dt>
        <dd>{profile.geography ?? "Not entered"}</dd>
      </div>
      <div className="review-wide">
        <dt>Problem</dt>
        <dd>{profile.problem ?? "Not entered"}</dd>
      </div>
      <div className="review-wide">
        <dt>Target audience</dt>
        <dd>{profile.target_audience ?? "Not entered"}</dd>
      </div>
      <div className="review-wide">
        <dt>Offer</dt>
        <dd>{profile.offer ?? "Not entered"}</dd>
      </div>
      <div>
        <dt>Goals</dt>
        <dd>{displayed(profile.goals)}</dd>
      </div>
      <div>
        <dt>Existing assets</dt>
        <dd>{displayed(profile.existing_assets)}</dd>
      </div>
      <div>
        <dt>Constraints</dt>
        <dd>{displayed(profile.constraints)}</dd>
      </div>
      <div>
        <dt>Budget</dt>
        <dd>{profile.budget ?? "Not entered"}</dd>
      </div>
      <div>
        <dt>Brand preferences</dt>
        <dd>{profile.brand_preferences ?? "Not entered"}</dd>
      </div>
      <div>
        <dt>Declared services</dt>
        <dd>{displayed(profile.connected_services)}</dd>
      </div>
    </dl>
  );
}

export default async function OnboardingPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; step?: string; updated?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const onboarding = await getOnboarding();
  const params = await searchParams;
  const requestedStep = Number(
    params.step ?? onboarding?.draft.current_step ?? 1,
  );
  const maxStep = onboarding?.draft.current_step ?? 1;
  const step = Number.isInteger(requestedStep)
    ? Math.min(Math.max(requestedStep, 1), maxStep)
    : 1;

  return (
    <main className="onboarding-shell">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">FOUNDORA / BUSINESS ONBOARDING</p>
          <h1>{onboarding?.draft.business_name ?? "Business profile"}</h1>
          <p className="lede">
            Capture founder-provided context, review its exact structured form,
            and explicitly approve what Foundora may treat as fact.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Workspace
          </Link>
          <Link className="text-link" href="/brain">
            Business brain
          </Link>
          <Link className="text-link" href="/agents">
            Agents
          </Link>
          <form action={logout}>
            <button className="button-secondary" type="submit">
              Sign out
            </button>
          </form>
        </nav>
      </header>

      {params.error && errors[params.error] ? (
        <p className="notice notice--error" role="alert">
          {errors[params.error]}
        </p>
      ) : null}
      {params.updated && updates[params.updated] ? (
        <p className="notice notice--success" role="status">
          {updates[params.updated]}
        </p>
      ) : null}
      {!onboarding ? (
        <p className="notice notice--error" role="alert">
          Onboarding could not be loaded. No profile data is being shown.
        </p>
      ) : null}

      {onboarding ? (
        <>
          <ol className="wizard-progress" aria-label="Onboarding progress">
            {steps.map((label, index) => {
              const number = index + 1;
              const accessible =
                onboarding.draft.status === "draft" && number <= maxStep;
              return (
                <li
                  className={number === step ? "wizard-current" : ""}
                  key={label}
                >
                  {accessible ? (
                    <Link href={`/onboarding?step=${number}`}>
                      <span>{number}</span> {label}
                    </Link>
                  ) : (
                    <span>
                      <span>{number}</span> {label}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>

          {onboarding.draft.status === "approved" &&
          onboarding.approved_profile ? (
            <section
              className="panel onboarding-card"
              aria-labelledby="approved-heading"
            >
              <p className="eyebrow">
                APPROVED FACTS / VERSION {onboarding.approved_profile.version}
              </p>
              <h2 id="approved-heading">Founder-approved business profile</h2>
              <p className="fact-boundary">
                Approved{" "}
                {new Date(
                  onboarding.approved_profile.approved_at,
                ).toLocaleString("en", { timeZone: "UTC" })}{" "}
                UTC. Declared services are context only; they are not verified
                connections.
              </p>
              <ReviewFields profile={onboarding.approved_profile} />
              <form action={reopenOnboarding}>
                <input
                  type="hidden"
                  name="revision"
                  value={onboarding.draft.revision}
                />
                <button className="button-secondary" type="submit">
                  Revise this profile
                </button>
              </form>
            </section>
          ) : onboarding.draft.status === "review" ? (
            <section
              className="panel onboarding-card"
              aria-labelledby="approval-heading"
            >
              <p className="eyebrow">FOUNDER REVIEW REQUIRED</p>
              <h2 id="approval-heading">Approve the exact profile below</h2>
              <p className="fact-boundary">
                This is a direct structure of your saved input. No AI gateway is
                active and no inferred value has been added.
                {onboarding.approved_profile
                  ? " Your prior approved version remains authoritative until this revision is approved."
                  : " Nothing here is an approved fact yet."}
              </p>
              <ReviewFields profile={onboarding.draft} />
              <div className="approval-actions">
                <form action={approveOnboarding}>
                  <input
                    type="hidden"
                    name="revision"
                    value={onboarding.draft.revision}
                  />
                  <button type="submit">Approve as business facts</button>
                </form>
                <form action={reopenOnboarding}>
                  <input
                    type="hidden"
                    name="revision"
                    value={onboarding.draft.revision}
                  />
                  <button className="button-secondary" type="submit">
                    Return to editing
                  </button>
                </form>
              </div>
            </section>
          ) : (
            <section
              className="panel onboarding-card"
              aria-labelledby="step-heading"
            >
              <p className="eyebrow">DRAFT / STEP {step} OF 5</p>
              <h2 id="step-heading">{steps[step - 1]}</h2>
              <p className="fact-boundary">
                Draft values are resumable but unapproved. Saving never promotes
                them to business facts.
              </p>

              {step === 1 ? (
                <form action={saveOnboardingFoundation}>
                  <input
                    type="hidden"
                    name="revision"
                    value={onboarding.draft.revision}
                  />
                  <label htmlFor="business-type">Business starting point</label>
                  <select
                    id="business-type"
                    name="business_type"
                    defaultValue={onboarding.draft.business_type ?? "idea"}
                  >
                    <option value="idea">Business idea</option>
                    <option value="existing">Existing business</option>
                  </select>
                  <label htmlFor="onboarding-name">Name</label>
                  <input
                    id="onboarding-name"
                    name="business_name"
                    defaultValue={onboarding.draft.business_name ?? ""}
                    maxLength={120}
                    required
                  />
                  <label htmlFor="industry">Industry</label>
                  <input
                    id="industry"
                    name="industry"
                    defaultValue={onboarding.draft.industry ?? ""}
                    maxLength={160}
                    required
                  />
                  <label htmlFor="geography">Geography</label>
                  <input
                    id="geography"
                    name="geography"
                    defaultValue={onboarding.draft.geography ?? ""}
                    maxLength={240}
                    required
                  />
                  <button type="submit">Save and continue</button>
                </form>
              ) : null}

              {step === 2 ? (
                <form action={saveOnboardingMarket}>
                  <input
                    type="hidden"
                    name="revision"
                    value={onboarding.draft.revision}
                  />
                  <label htmlFor="problem">Problem</label>
                  <textarea
                    id="problem"
                    name="problem"
                    defaultValue={onboarding.draft.problem ?? ""}
                    maxLength={4000}
                    rows={5}
                    required
                  />
                  <label htmlFor="target-audience">Target audience</label>
                  <textarea
                    id="target-audience"
                    name="target_audience"
                    defaultValue={onboarding.draft.target_audience ?? ""}
                    maxLength={4000}
                    rows={5}
                    required
                  />
                  <label htmlFor="offer">Offer</label>
                  <textarea
                    id="offer"
                    name="offer"
                    defaultValue={onboarding.draft.offer ?? ""}
                    maxLength={4000}
                    rows={5}
                    required
                  />
                  <button type="submit">Save and continue</button>
                </form>
              ) : null}

              {step === 3 ? (
                <form action={saveOnboardingExecution}>
                  <input
                    type="hidden"
                    name="revision"
                    value={onboarding.draft.revision}
                  />
                  <label htmlFor="onboarding-goals">Goals — one per line</label>
                  <textarea
                    id="onboarding-goals"
                    name="goals"
                    defaultValue={lineValues(onboarding.draft.goals)}
                    maxLength={7525}
                    rows={5}
                    required
                  />
                  <label htmlFor="existing-assets">
                    Existing assets — one per line, blank if none
                  </label>
                  <textarea
                    id="existing-assets"
                    name="existing_assets"
                    defaultValue={lineValues(onboarding.draft.existing_assets)}
                    maxLength={15050}
                    rows={4}
                  />
                  <label htmlFor="constraints">
                    Constraints — one per line, blank if none
                  </label>
                  <textarea
                    id="constraints"
                    name="constraints"
                    defaultValue={lineValues(onboarding.draft.constraints)}
                    maxLength={15050}
                    rows={4}
                  />
                  <label htmlFor="budget">Budget and spending context</label>
                  <textarea
                    id="budget"
                    name="budget"
                    defaultValue={onboarding.draft.budget ?? ""}
                    maxLength={2000}
                    rows={4}
                    required
                  />
                  <button type="submit">Save and continue</button>
                </form>
              ) : null}

              {step === 4 ? (
                <form action={saveOnboardingBrandServices}>
                  <input
                    type="hidden"
                    name="revision"
                    value={onboarding.draft.revision}
                  />
                  <label htmlFor="brand-preferences">Brand preferences</label>
                  <textarea
                    id="brand-preferences"
                    name="brand_preferences"
                    defaultValue={onboarding.draft.brand_preferences ?? ""}
                    maxLength={4000}
                    rows={6}
                    required
                  />
                  <label htmlFor="connected-services">
                    Services already used — one per line, blank if none
                  </label>
                  <textarea
                    id="connected-services"
                    name="connected_services"
                    defaultValue={lineValues(
                      onboarding.draft.connected_services,
                    )}
                    maxLength={15050}
                    rows={5}
                  />
                  <p className="fine-print">
                    Listing a service records a founder declaration only.
                    Foundora does not claim it is authenticated or connected.
                  </p>
                  <button type="submit">Save and review</button>
                </form>
              ) : null}

              {step === 5 ? (
                <>
                  <ReviewFields profile={onboarding.draft} />
                  <p className="fact-boundary">
                    Submit freezes this revision for a separate approval
                    decision. It does not approve it.
                  </p>
                  <form action={submitOnboarding}>
                    <input
                      type="hidden"
                      name="revision"
                      value={onboarding.draft.revision}
                    />
                    <button type="submit">Submit for founder review</button>
                  </form>
                </>
              ) : null}
            </section>
          )}
        </>
      ) : null}
    </main>
  );
}
