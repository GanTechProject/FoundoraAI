import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBrandDashboard } from "../../lib/brand";
import { getBusinesses } from "../../lib/businesses";
import { approveBrand, logout } from "../actions";

export const dynamic = "force-dynamic";

const messages: Record<string, string> = {
  approved: "The selected brand system is now founder-approved business data.",
};
const errors: Record<string, string> = {
  conflict:
    "The active brand system changed. Reload and review the current version.",
  invalid:
    "That run is not a valid proposal tied to the current approved strategy and offer.",
  unavailable: "Brand state is temporarily unavailable.",
};
const sectionLabels: Record<string, string> = {
  brand_strategy: "Brand strategy",
  positioning: "Positioning",
  naming_analysis: "Naming analysis",
  voice: "Voice",
  messaging: "Messaging",
  visual_direction: "Visual direction",
  brand_rules: "Brand rules",
  asset_references: "Asset references",
};

function records(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          typeof item === "object" && item !== null,
      )
    : [];
}

export default async function BrandPage({
  searchParams,
}: {
  searchParams: Promise<{ updated?: string; error?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const dashboard = await getBrandDashboard();
  const params = await searchParams;

  return (
    <main className="settings-shell agents-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / BRAND SYSTEM</p>
          <h1>Approved rules, reusable brand direction</h1>
          <p className="lede">
            Brand proposals inherit the current approved strategy and offer.
            Every rule remains traceable, names remain unchecked, assets remain
            proposed references, and only explicit founder approval makes the
            system authoritative.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/agents">
            Agents
          </Link>
          <Link className="text-link" href="/strategy">
            Strategy
          </Link>
          <Link className="text-link" href="/products-offers">
            Products &amp; offers
          </Link>
          <Link className="text-link" href="/brain">
            Business brain
          </Link>
          <form action={logout}>
            <button className="button-secondary" type="submit">
              Sign out
            </button>
          </form>
        </nav>
      </header>

      {params.updated && messages[params.updated] ? (
        <p className="notice notice--success">{messages[params.updated]}</p>
      ) : null}
      {params.error && errors[params.error] ? (
        <p className="notice notice--error">{errors[params.error]}</p>
      ) : null}
      {!dashboard ? (
        <p className="notice notice--error">Brand state could not be loaded.</p>
      ) : null}

      {dashboard ? (
        <>
          <section className="panel">
            <p className="eyebrow">FOUNDER APPROVAL</p>
            <h2>Completed proposals</h2>
            {dashboard.candidate_runs.length ? (
              dashboard.candidate_runs.map((run) => (
                <form
                  className="agent-run-form"
                  action={approveBrand}
                  key={run.run_id}
                >
                  <input type="hidden" name="run_id" value={run.run_id} />
                  <input
                    type="hidden"
                    name="expected_version"
                    value={dashboard.current_version}
                  />
                  <strong>{run.brand_title}</strong>
                  <code>{run.run_id}</code>
                  <span>
                    Strategy v{run.source_strategy_version} · offer v
                    {run.source_product_offer_version}
                  </span>
                  <button
                    type="submit"
                    disabled={
                      dashboard.current?.source_agent_run_id === run.run_id
                    }
                  >
                    {dashboard.current?.source_agent_run_id === run.run_id
                      ? "Current approved brand"
                      : "Approve after review"}
                  </button>
                </form>
              ))
            ) : (
              <p>
                No completed Brand Strategist proposal is ready. Approve a
                strategy and product/offer portfolio, then queue the agent.
              </p>
            )}
          </section>

          <section className="panel">
            <p className="eyebrow">ACTIVE BRAND SYSTEM</p>
            <h2>
              {dashboard.current
                ? `${String(dashboard.current.brand_system.brand_title ?? "Brand system")} · version ${dashboard.current.version}`
                : "Not approved yet"}
            </h2>
            {dashboard.current ? (
              <>
                <p>
                  <strong>Tagline:</strong>{" "}
                  {String(
                    (
                      dashboard.current.brand_system.tagline as
                        Record<string, unknown> | undefined
                    )?.statement ?? "No tagline recorded",
                  )}
                </p>
                <p className="fine-print">
                  Active · strategy v{dashboard.current.source_strategy_version}{" "}
                  · offer v{dashboard.current.source_product_offer_version} ·
                  run <code>{dashboard.current.source_agent_run_id}</code>
                </p>
                <div className="agent-registry">
                  {Object.entries(sectionLabels).map(([key, label]) => (
                    <article className="panel agent-card" key={key}>
                      <h3>{label}</h3>
                      <ul>
                        {records(dashboard.current?.brand_system[key]).map(
                          (item) => (
                            <li key={String(item.item_id)}>
                              {String(item.statement)}
                            </li>
                          ),
                        )}
                      </ul>
                    </article>
                  ))}
                </div>
              </>
            ) : (
              <p>No brand system has received founder approval.</p>
            )}
          </section>

          <section className="panel">
            <p className="eyebrow">VERSION HISTORY</p>
            <h2>Immutable approvals</h2>
            {dashboard.versions.length ? (
              <ul>
                {dashboard.versions.map((item) => (
                  <li key={item.id}>
                    Version {item.version} · {item.status} · strategy v
                    {item.source_strategy_version} · offer v
                    {item.source_product_offer_version}
                  </li>
                ))}
              </ul>
            ) : (
              <p>No approved versions exist.</p>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
