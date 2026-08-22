import Link from "next/link";
import { redirect } from "next/navigation";

import { getActiveSessions, getAuthSession } from "../../../lib/auth";
import { changePassword, logout, revokeOtherSessions } from "../../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  confirmation: "The new password confirmation does not match.",
  current: "The current password is incorrect.",
  password: "Use a password between 15 and 128 characters.",
  session: "The other sessions could not be revoked.",
  unavailable: "The security service is temporarily unavailable.",
};

const updates: Record<string, string> = {
  password: "Password changed and every previous session was revoked.",
  sessions: "Every other active session was revoked.",
};

function timestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

export default async function SecuritySettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; updated?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const sessions = await getActiveSessions();
  const { error, updated } = await searchParams;

  return (
    <main className="settings-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / SECURITY</p>
          <h1>Owner settings</h1>
          <p className="lede">Authenticated as {auth.owner.email}</p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Business workspace
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

      <div className="settings-grid">
        <section className="panel" aria-labelledby="password-heading">
          <p className="eyebrow">CREDENTIAL</p>
          <h2 id="password-heading">Change password</h2>
          <form action={changePassword}>
            <label htmlFor="current-password">Current password</label>
            <input
              id="current-password"
              name="current_password"
              type="password"
              autoComplete="current-password"
              maxLength={128}
              required
            />
            <label htmlFor="new-password">New password</label>
            <input
              id="new-password"
              name="new_password"
              type="password"
              autoComplete="new-password"
              minLength={15}
              maxLength={128}
              required
            />
            <label htmlFor="confirm-password">Confirm new password</label>
            <input
              id="confirm-password"
              name="confirm_password"
              type="password"
              autoComplete="new-password"
              minLength={15}
              maxLength={128}
              required
            />
            <button type="submit">Update password</button>
          </form>
        </section>

        <section className="panel" aria-labelledby="sessions-heading">
          <p className="eyebrow">SESSION LIFECYCLE</p>
          <h2 id="sessions-heading">Active sessions</h2>
          {sessions ? (
            <ul className="session-list">
              {sessions.map((session) => (
                <li key={session.id}>
                  <div>
                    <strong>
                      {session.current ? "This session" : "Other session"}
                    </strong>
                    <span>{session.user_agent ?? "Unknown client"}</span>
                  </div>
                  <time dateTime={session.last_seen_at}>
                    Seen {timestamp(session.last_seen_at)} UTC
                  </time>
                </li>
              ))}
            </ul>
          ) : (
            <p className="notice notice--error" role="status">
              Active sessions could not be verified.
            </p>
          )}
          <form action={revokeOtherSessions}>
            <button className="button-secondary" type="submit">
              Revoke other sessions
            </button>
          </form>
          <p className="fine-print">
            Password changes revoke every prior session and issue a fresh token
            for this browser.
          </p>
        </section>
      </div>
    </main>
  );
}
