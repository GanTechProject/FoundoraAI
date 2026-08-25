import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { getWebsiteSpecificationDashboard } from "../../lib/website-specifications";
import { approveWebsiteSpecification, logout } from "../actions";

export const dynamic = "force-dynamic";

const messages: Record<string, string> = {
  approved:
    "The selected website specification is now founder-approved business data.",
};
const errors: Record<string, string> = {
  conflict:
    "The active website specification changed. Reload and review the current version.",
  invalid:
    "That run is not a complete proposal tied to the current strategy, offer, and brand.",
  unavailable: "Website specification state is temporarily unavailable.",
};
const requirementLabels: Record<string, string> = {
  conversion_goals: "Conversion goals",
  seo_requirements: "SEO requirements",
  content_requirements: "Content requirements",
  brand_constraints: "Brand constraints",
  technical_requirements: "Technical requirements",
};

function records(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          typeof item === "object" && item !== null,
      )
    : [];
}

export default async function WebsiteSpecificationsPage({
  searchParams,
}: {
  searchParams: Promise<{ updated?: string; error?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const dashboard = await getWebsiteSpecificationDashboard();
  const params = await searchParams;

  return (
    <main className="settings-shell agents-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / WEBSITE SPECIFICATIONS</p>
          <h1>Complete direction before a single line of code</h1>
          <p className="lede">
            Specifications inherit the exact approved strategy, offer, and
            brand. They define every page and requirement for founder review;
            repository access, code generation, builds, and deployment remain
            explicitly outside this phase.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/agents">
            Agents
          </Link>
          <Link className="text-link" href="/website-projects">
            Website projects
          </Link>
          <Link className="text-link" href="/brand">
            Brand
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
        <p className="notice notice--error">
          Website specification state could not be loaded.
        </p>
      ) : null}

      {dashboard ? (
        <>
          <section className="panel">
            <p className="eyebrow">FOUNDER REVIEW</p>
            <h2>Completed proposals</h2>
            {dashboard.candidate_runs.length ? (
              dashboard.candidate_runs.map((run) => (
                <form
                  className="agent-run-form"
                  action={approveWebsiteSpecification}
                  key={run.run_id}
                >
                  <input type="hidden" name="run_id" value={run.run_id} />
                  <input
                    type="hidden"
                    name="expected_version"
                    value={dashboard.current_version}
                  />
                  <strong>{run.project_title}</strong>
                  <code>{run.run_id}</code>
                  <span>
                    Strategy v{run.source_strategy_version} · offer v
                    {run.source_product_offer_version} · brand v
                    {run.source_brand_version}
                  </span>
                  <button
                    type="submit"
                    disabled={
                      dashboard.current?.source_agent_run_id === run.run_id
                    }
                  >
                    {dashboard.current?.source_agent_run_id === run.run_id
                      ? "Current approved specification"
                      : "Approve after review"}
                  </button>
                </form>
              ))
            ) : (
              <p>
                No completed Website Specification proposal is ready. Approve
                aligned strategy, offer, and brand versions, then queue the
                specification agent.
              </p>
            )}
          </section>

          <section className="panel">
            <p className="eyebrow">ACTIVE SPECIFICATION</p>
            <h2>
              {dashboard.current
                ? `${String(dashboard.current.specification.project_title ?? "Website specification")} · version ${dashboard.current.version}`
                : "Not approved yet"}
            </h2>
            {dashboard.current ? (
              <>
                <p>
                  <strong>Site objective:</strong>{" "}
                  {String(
                    (
                      dashboard.current.specification.site_objective as
                        Record<string, unknown> | undefined
                    )?.statement ?? "No site objective recorded",
                  )}
                </p>
                <p className="fine-print">
                  Code generation:{" "}
                  <strong>
                    {String(
                      dashboard.current.specification.code_generation_status ??
                        "not_started",
                    )}
                  </strong>{" "}
                  · strategy v{dashboard.current.source_strategy_version} ·
                  offer v{dashboard.current.source_product_offer_version} ·
                  brand v{dashboard.current.source_brand_version}
                </p>

                <section className="panel">
                  <h3>Sitemap and page specifications</h3>
                  <ul>
                    {records(dashboard.current.specification.sitemap).map(
                      (page) => (
                        <li key={String(page.page_id)}>
                          <code>{String(page.path)}</code> —{" "}
                          {String(page.label)}
                        </li>
                      ),
                    )}
                  </ul>
                  <div className="agent-registry">
                    {records(dashboard.current.specification.page_specs).map(
                      (page) => (
                        <article
                          className="panel agent-card"
                          key={String(page.page_id)}
                        >
                          <h3>{String(page.page_name)}</h3>
                          <code>{String(page.path)}</code>
                          <p>{String(page.purpose)}</p>
                          <p className="fine-print">
                            {records(page.sections).length} specified sections
                          </p>
                        </article>
                      ),
                    )}
                  </div>
                </section>

                <div className="agent-registry">
                  {Object.entries(requirementLabels).map(([key, label]) => (
                    <article className="panel agent-card" key={key}>
                      <h3>{label}</h3>
                      <ul>
                        {records(dashboard.current?.specification[key]).map(
                          (item) => (
                            <li key={String(item.item_id ?? item.goal_id)}>
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
              <p>No website specification has received founder approval.</p>
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
                    {item.source_product_offer_version} · brand v
                    {item.source_brand_version}
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
