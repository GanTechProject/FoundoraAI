import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses, getWorkspace } from "../../lib/businesses";
import {
  addBusinessGoal,
  archiveBusiness,
  createBusiness,
  logout,
  selectBusiness,
  updateBusinessGoalStatus,
  updateBusinessPreferences,
  updateBusinessProfile,
  updateBusinessStatus,
} from "../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  "archive-confirmation":
    "Type ARCHIVE exactly before archiving this business.",
  conflict: "Each business needs a distinct name.",
  invalid: "Review the submitted fields and try again.",
  session: "Your session expired. Sign in again.",
  unavailable: "The business workspace is temporarily unavailable.",
};

const updates: Record<string, string> = {
  archived:
    "Business archived. Its operational workspace is no longer selectable.",
  created: "Business created and selected when no prior selection existed.",
  goal: "Business goal updated.",
  preferences: "Business preferences updated.",
  profile: "Business profile updated.",
  selected:
    "Business context switched. All workspace data now uses this business.",
  status: "Business status updated.",
};

export default async function WorkspacePage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; updated?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const collection = await getBusinesses();
  const workspace = collection?.selected_business_id
    ? await getWorkspace()
    : null;
  const { error, updated } = await searchParams;
  const activeBusinesses =
    collection?.businesses.filter((business) => !business.archived_at) ?? [];
  const archivedBusinesses =
    collection?.businesses.filter((business) => business.archived_at) ?? [];

  return (
    <main className="workspace-shell">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">FOUNDORA / BUSINESS WORKSPACE</p>
          <h1>{workspace?.business.name ?? "Choose your business context"}</h1>
          <p className="lede">
            {workspace
              ? "Profile, operating preferences, and goals are isolated to this selected business."
              : "Create or select an active business to open its isolated workspace."}
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          {workspace ? (
            <>
              <Link className="text-link" href="/onboarding">
                Onboarding
              </Link>
              <Link className="text-link" href="/brain">
                Business brain
              </Link>
              <Link className="text-link" href="/agents">
                Agents
              </Link>
              <Link className="text-link" href="/tasks">
                Tasks
              </Link>
              <Link className="text-link" href="/workflows">
                Workflows
              </Link>
              <Link className="text-link" href="/settings/ai">
                AI gateway
              </Link>
            </>
          ) : null}
          <Link className="text-link" href="/settings/security">
            Security
          </Link>
          <form action={logout}>
            <button className="button-secondary" type="submit">
              Sign out
            </button>
          </form>
        </nav>
      </header>

      {error && errors[error] ? (
        <p className="notice notice--error" role="alert">
          {errors[error]}
        </p>
      ) : null}
      {updated && updates[updated] ? (
        <p className="notice notice--success" role="status">
          {updates[updated]}
        </p>
      ) : null}
      {!collection ? (
        <p className="notice notice--error" role="alert">
          The business registry could not be loaded. No workspace data is being
          shown.
        </p>
      ) : null}

      <section className="context-bar" aria-labelledby="context-heading">
        <div>
          <p className="eyebrow">SELECTED CONTEXT</p>
          <h2 id="context-heading">Business switcher</h2>
        </div>
        {activeBusinesses.length ? (
          <div className="business-switcher">
            {activeBusinesses.map((business) => (
              <form action={selectBusiness} key={business.id}>
                <input type="hidden" name="business_id" value={business.id} />
                <button
                  className={
                    business.selected ? "context-active" : "button-secondary"
                  }
                  type="submit"
                  disabled={business.selected}
                >
                  {business.name}
                </button>
              </form>
            ))}
          </div>
        ) : (
          <p className="fine-print">No active businesses yet.</p>
        )}
      </section>

      <div className="workspace-grid">
        <section className="panel" aria-labelledby="create-heading">
          <p className="eyebrow">BUSINESS REGISTRY</p>
          <h2 id="create-heading">Create another business</h2>
          <form action={createBusiness}>
            <label htmlFor="create-name">Business name</label>
            <input
              id="create-name"
              name="name"
              minLength={1}
              maxLength={120}
              required
            />
            <label htmlFor="create-summary">Short profile summary</label>
            <textarea
              id="create-summary"
              name="summary"
              maxLength={2000}
              rows={4}
            />
            <button type="submit">Create business</button>
          </form>
          {archivedBusinesses.length ? (
            <div className="archived-list">
              <p className="fine-print">Archived businesses</p>
              <ul>
                {archivedBusinesses.map((business) => (
                  <li key={business.id}>
                    <span>{business.name}</span>
                    <span>Archived</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>

        {workspace ? (
          <>
            <section className="panel" aria-labelledby="profile-heading">
              <p className="eyebrow">PROFILE</p>
              <h2 id="profile-heading">Business profile</h2>
              <form action={updateBusinessProfile}>
                <label htmlFor="profile-name">Business name</label>
                <input
                  id="profile-name"
                  name="name"
                  defaultValue={workspace.business.name}
                  minLength={1}
                  maxLength={120}
                  required
                />
                <label htmlFor="profile-summary">Summary</label>
                <textarea
                  id="profile-summary"
                  name="summary"
                  defaultValue={workspace.business.summary ?? ""}
                  maxLength={2000}
                  rows={5}
                />
                <button type="submit">Save profile</button>
              </form>
            </section>

            <section className="panel" aria-labelledby="status-heading">
              <p className="eyebrow">LIFECYCLE</p>
              <h2 id="status-heading">Business status</h2>
              <form action={updateBusinessStatus}>
                <label htmlFor="business-status">Current operating state</label>
                <select
                  id="business-status"
                  name="status"
                  defaultValue={workspace.business.status}
                >
                  <option value="planning">Planning</option>
                  <option value="active">Active</option>
                  <option value="paused">Paused</option>
                </select>
                <button type="submit">Update status</button>
              </form>
              <p className="fine-print">
                Status describes the active workspace. Archiving removes it from
                every session&apos;s selectable context.
              </p>
            </section>

            <section className="panel" aria-labelledby="preferences-heading">
              <p className="eyebrow">OPERATING DEFAULTS</p>
              <h2 id="preferences-heading">Preferences</h2>
              <form action={updateBusinessPreferences}>
                <label htmlFor="timezone">IANA timezone</label>
                <input
                  id="timezone"
                  name="timezone"
                  defaultValue={workspace.preferences.timezone}
                  maxLength={64}
                  required
                />
                <label htmlFor="currency">Currency</label>
                <input
                  id="currency"
                  name="currency"
                  defaultValue={workspace.preferences.currency}
                  minLength={3}
                  maxLength={3}
                  required
                />
                <label htmlFor="locale">Locale</label>
                <input
                  id="locale"
                  name="locale"
                  defaultValue={workspace.preferences.locale}
                  maxLength={35}
                  required
                />
                <button type="submit">Save preferences</button>
              </form>
            </section>

            <section
              className="panel panel--wide"
              aria-labelledby="goals-heading"
            >
              <p className="eyebrow">DIRECTION</p>
              <h2 id="goals-heading">Business goals</h2>
              <form className="goal-form" action={addBusinessGoal}>
                <div>
                  <label htmlFor="goal-title">Goal</label>
                  <input
                    id="goal-title"
                    name="title"
                    maxLength={200}
                    required
                  />
                </div>
                <div>
                  <label htmlFor="target-date">Target date</label>
                  <input id="target-date" name="target_date" type="date" />
                </div>
                <div className="goal-details">
                  <label htmlFor="goal-details">Details</label>
                  <textarea
                    id="goal-details"
                    name="details"
                    maxLength={2000}
                    rows={3}
                  />
                </div>
                <button type="submit">Add goal</button>
              </form>
              {workspace.goals.length ? (
                <ul className="goal-list">
                  {workspace.goals.map((goal) => (
                    <li key={goal.id}>
                      <div>
                        <strong>{goal.title}</strong>
                        {goal.details ? <span>{goal.details}</span> : null}
                        {goal.target_date ? (
                          <time dateTime={goal.target_date}>
                            Target {goal.target_date}
                          </time>
                        ) : null}
                      </div>
                      <form
                        action={updateBusinessGoalStatus.bind(null, goal.id)}
                      >
                        <select
                          name="status"
                          defaultValue={goal.status}
                          aria-label={`Status for ${goal.title}`}
                        >
                          <option value="active">Active</option>
                          <option value="completed">Completed</option>
                          <option value="cancelled">Cancelled</option>
                        </select>
                        <button className="button-secondary" type="submit">
                          Save
                        </button>
                      </form>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="fine-print">
                  No goals recorded for this business.
                </p>
              )}
            </section>

            <section
              className="panel panel--danger"
              aria-labelledby="archive-heading"
            >
              <p className="eyebrow">ARCHIVE</p>
              <h2 id="archive-heading">Close this workspace</h2>
              <p className="fine-print">
                Archived businesses remain in the registry for historical
                integrity but cannot be selected. Type ARCHIVE to continue.
              </p>
              <form action={archiveBusiness}>
                <label htmlFor="archive-confirmation">Confirmation</label>
                <input
                  id="archive-confirmation"
                  name="confirmation"
                  autoComplete="off"
                  required
                />
                <button className="button-danger" type="submit">
                  Archive {workspace.business.name}
                </button>
              </form>
            </section>
          </>
        ) : null}
      </div>
    </main>
  );
}
