import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { getStrategyDashboard } from "../../lib/strategy";
import { approveStrategy, logout } from "../actions";

export const dynamic = "force-dynamic";

const sectionLabels: Record<string, string> = {
  opportunity_assessment: "Opportunity assessment",
  value_proposition: "Value proposition",
  business_model: "Business model",
  pricing_hypotheses: "Pricing hypotheses",
  positioning: "Positioning",
  go_to_market: "Go-to-market",
  launch_roadmap: "Launch roadmap",
  risks: "Risks",
  assumptions_requiring_validation: "Assumptions requiring validation",
};

const messages: Record<string, string> = {
  approved: "The selected evidence-valid strategy is now founder-approved.",
};
const errors: Record<string, string> = {
  conflict:
    "The approved strategy changed. Reload and review the current version.",
  invalid:
    "That run is not a completed, evidence-valid Business Strategist proposal.",
  unavailable: "Strategy state is temporarily unavailable.",
};

export default async function StrategyPage({
  searchParams,
}: {
  searchParams: Promise<{ updated?: string; error?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const dashboard = await getStrategyDashboard();
  const params = await searchParams;

  return (
    <main className="settings-shell agents-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / BUSINESS STRATEGY</p>
          <h1>Evidence first, founder approval second</h1>
          <p className="lede">
            Business Strategist proposals must cover all nine strategy artifacts
            and tie every item to approved business facts and validated
            research. Approval is explicit; pricing and validation assumptions
            remain hypotheses.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/agents">
            Agents
          </Link>
          <Link className="text-link" href="/brain">
            Business brain
          </Link>
          <Link className="text-link" href="/products-offers">
            Products &amp; offers
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
          Strategy state could not be loaded.
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
                  action={approveStrategy}
                  key={run.run_id}
                >
                  <input type="hidden" name="run_id" value={run.run_id} />
                  <input
                    type="hidden"
                    name="expected_version"
                    value={dashboard.current_version}
                  />
                  <strong>{run.strategy_title}</strong>
                  <code>{run.run_id}</code>
                  <span>Context {run.context_id}</span>
                  <button
                    type="submit"
                    disabled={
                      dashboard.approved?.source_agent_run_id === run.run_id
                    }
                  >
                    {dashboard.approved?.source_agent_run_id === run.run_id
                      ? "Current approved strategy"
                      : "Approve after review"}
                  </button>
                </form>
              ))
            ) : (
              <p>
                No completed Business Strategist proposal is ready for approval.
              </p>
            )}
          </section>

          <section className="panel">
            <p className="eyebrow">APPROVED STRATEGY</p>
            <h2>
              {dashboard.approved
                ? `Version ${dashboard.approved.version}`
                : "Not approved yet"}
            </h2>
            {dashboard.approved ? (
              <>
                <p>
                  <strong>
                    {String(
                      dashboard.approved.strategy.strategy_title ??
                        "Business strategy",
                    )}
                  </strong>
                </p>
                <p className="fine-print">
                  Source run{" "}
                  <code>{dashboard.approved.source_agent_run_id}</code> ·
                  context <code>{dashboard.approved.context_id}</code>
                </p>
                <div className="agent-registry">
                  {Object.entries(sectionLabels).map(([key, label]) => {
                    const items = dashboard.approved?.strategy[key];
                    return (
                      <article className="panel agent-card" key={key}>
                        <h3>{label}</h3>
                        {Array.isArray(items) ? (
                          <ul>
                            {items.map((item, index) => (
                              <li key={`${key}-${index}`}>
                                {typeof item === "object" && item !== null
                                  ? String(
                                      (item as Record<string, unknown>)
                                        .statement ?? "",
                                    )
                                  : ""}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p>No item recorded.</p>
                        )}
                      </article>
                    );
                  })}
                </div>
              </>
            ) : (
              <p>
                Run all three research specialists, queue Business Strategist,
                review its proposal, then approve it here.
              </p>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
