import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { getProductOfferDashboard } from "../../lib/product-offers";
import { approveProductOffer, logout } from "../actions";

export const dynamic = "force-dynamic";

const messages: Record<string, string> = {
  approved: "The selected portfolio is now founder-approved business data.",
};
const errors: Record<string, string> = {
  conflict:
    "The active portfolio changed. Reload and review the current version.",
  invalid:
    "That run is not a valid proposal tied to the current approved strategy.",
  unavailable: "Product and offer state is temporarily unavailable.",
};

function records(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          typeof item === "object" && item !== null,
      )
    : [];
}

export default async function ProductsOffersPage({
  searchParams,
}: {
  searchParams: Promise<{ updated?: string; error?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const dashboard = await getProductOfferDashboard();
  const params = await searchParams;

  return (
    <main className="settings-shell agents-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / PRODUCTS &amp; OFFERS</p>
          <h1>Traceable offers, explicit founder approval</h1>
          <p className="lede">
            Proposals inherit the current approved strategy and keep every
            segment, product, benefit, package, and price traceable. Approval
            creates an immutable active version; prices remain marked for
            validation.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/agents">
            Agents
          </Link>
          <Link className="text-link" href="/strategy">
            Strategy
          </Link>
          <Link className="text-link" href="/brain">
            Business brain
          </Link>
          <Link className="text-link" href="/workspace">
            Workspace
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
        <p className="notice notice--error">
          Product and offer state could not be loaded.
        </p>
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
                  action={approveProductOffer}
                  key={run.run_id}
                >
                  <input type="hidden" name="run_id" value={run.run_id} />
                  <input
                    type="hidden"
                    name="expected_version"
                    value={dashboard.current_version}
                  />
                  <strong>{run.portfolio_name}</strong>
                  <code>{run.run_id}</code>
                  <span>Approved strategy v{run.source_strategy_version}</span>
                  <button
                    type="submit"
                    disabled={
                      dashboard.current?.source_agent_run_id === run.run_id
                    }
                  >
                    {dashboard.current?.source_agent_run_id === run.run_id
                      ? "Current approved portfolio"
                      : "Approve after review"}
                  </button>
                </form>
              ))
            ) : (
              <p>
                No completed Product &amp; Offer Agent proposal is ready.
                Approve a strategy, then queue the agent from the AI Team.
              </p>
            )}
          </section>

          <section className="panel">
            <p className="eyebrow">ACTIVE PORTFOLIO</p>
            <h2>
              {dashboard.current
                ? `${String(dashboard.current.portfolio.portfolio_name ?? "Portfolio")} · version ${dashboard.current.version}`
                : "Not approved yet"}
            </h2>
            {dashboard.current ? (
              <>
                <p className="fine-print">
                  Active · source strategy v
                  {dashboard.current.source_strategy_version} · run{" "}
                  <code>{dashboard.current.source_agent_run_id}</code>
                </p>
                <div className="agent-registry">
                  <article className="panel agent-card">
                    <h3>Target segments</h3>
                    <ul>
                      {records(dashboard.current.portfolio.target_segments).map(
                        (item) => (
                          <li key={String(item.segment_id)}>
                            <strong>{String(item.name)}</strong> —{" "}
                            {String(item.description)}
                          </li>
                        ),
                      )}
                    </ul>
                  </article>
                  <article className="panel agent-card">
                    <h3>Products &amp; services</h3>
                    <ul>
                      {records(
                        dashboard.current.portfolio.products_services,
                      ).map((item) => (
                        <li key={String(item.product_id)}>
                          <strong>{String(item.name)}</strong> (
                          {String(item.kind)}) — {String(item.description)}
                        </li>
                      ))}
                    </ul>
                  </article>
                  <article className="panel agent-card">
                    <h3>Packages &amp; pricing</h3>
                    <ul>
                      {records(dashboard.current.portfolio.packages).map(
                        (item) => {
                          const pricing =
                            typeof item.pricing === "object" &&
                            item.pricing !== null
                              ? (item.pricing as Record<string, unknown>)
                              : {};
                          return (
                            <li key={String(item.package_id)}>
                              <strong>{String(item.name)}</strong> —{" "}
                              {String(pricing.currency)}{" "}
                              {(Number(pricing.amount_minor) / 100).toFixed(2)}{" "}
                              / {String(pricing.billing_period)} (requires
                              validation)
                            </li>
                          );
                        },
                      )}
                    </ul>
                  </article>
                </div>
              </>
            ) : (
              <p>No portfolio has received founder approval.</p>
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
                    {item.source_strategy_version}
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
