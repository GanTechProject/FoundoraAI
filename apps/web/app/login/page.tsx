import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { login } from "../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  invalid: "The email or password is incorrect.",
  limited: "Too many attempts. Wait before trying again.",
  unavailable: "Authentication is temporarily unavailable.",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  if (await getAuthSession()) redirect("/settings/security");
  const { error } = await searchParams;

  return (
    <main className="auth-shell">
      <section className="auth-intro" aria-labelledby="login-title">
        <p className="eyebrow">FOUNDORA / OWNER ACCESS</p>
        <h1 id="login-title">Your business operating system.</h1>
        <p className="lede">
          Sign in with the owner account provisioned from the server. Foundora
          has no public registration or organization accounts.
        </p>
      </section>

      <section className="panel" aria-label="Owner sign in">
        <div>
          <p className="eyebrow">SECURE SESSION</p>
          <h2>Sign in</h2>
        </div>
        {error && errors[error] ? (
          <p className="notice notice--error" role="alert">
            {errors[error]}
          </p>
        ) : null}
        <form action={login}>
          <label htmlFor="email">Owner email</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="username"
            maxLength={320}
            required
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            maxLength={128}
            required
          />
          <button type="submit">Enter Foundora</button>
        </form>
        <p className="fine-print">
          Sessions expire after 30 minutes of inactivity and always after eight
          hours.
        </p>
      </section>
    </main>
  );
}
