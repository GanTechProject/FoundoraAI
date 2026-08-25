import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { getWebsiteProjectDashboard } from "../../lib/website-projects";
import { logout, startWebsiteProject } from "../actions";

export const dynamic = "force-dynamic";

const messages: Record<string, string> = {
  queued:
    "The controlled website build was queued. Refresh to inspect its result.",
};
const errors: Record<string, string> = {
  invalid:
    "The approved specification or exact modification base is unavailable. Reload and review the boundary.",
  unavailable: "Website project state is temporarily unavailable.",
};

function timestamp(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value));
}

export default async function WebsiteProjectsPage({
  searchParams,
}: {
  searchParams: Promise<{ updated?: string; error?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const dashboard = await getWebsiteProjectDashboard();
  const params = await searchParams;
  const current = dashboard?.current_project ?? null;

  return (
    <main className="settings-shell agents-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / WEBSITE PROJECTS</p>
          <h1>Controlled source changes, computed build truth</h1>
          <p className="lede">
            The Website/Coding Agent works only from the exact founder-approved
            specification. It proposes bounded source changes; reviewed internal
            tools apply them and compute build, test, lint, accessibility, SEO,
            and performance evidence. Generated processes, deployment, domains,
            publication, and production credentials remain unavailable.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/website-specifications">
            Website specification
          </Link>
          <Link className="text-link" href="/agents">
            Agents
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
          Website project state could not be loaded.
        </p>
      ) : null}

      {dashboard ? (
        <>
          <section className="panel">
            <p className="eyebrow">CONTROLLED BUILD</p>
            <h2>
              {dashboard.next_operation === "modify"
                ? "Modify the current verified project"
                : "Generate from the approved specification"}
            </h2>
            {dashboard.blocker ? (
              <p className="notice notice--warning">{dashboard.blocker}</p>
            ) : (
              <form className="agent-run-form" action={startWebsiteProject}>
                <input
                  type="hidden"
                  name="operation"
                  value={dashboard.next_operation ?? "generate"}
                />
                {dashboard.next_operation === "modify" && current ? (
                  <input
                    type="hidden"
                    name="base_project_version"
                    value={current.version}
                  />
                ) : null}
                <label htmlFor="website-project-objective">
                  Founder implementation objective
                </label>
                <textarea
                  id="website-project-objective"
                  name="objective"
                  defaultValue={
                    dashboard.next_operation === "modify"
                      ? "Improve the current website while preserving every approved specification requirement and passing every controlled check."
                      : "Generate the complete provider-neutral website from the current approved specification and satisfy every controlled check."
                  }
                  minLength={1}
                  maxLength={500}
                  rows={4}
                  required
                />
                <button type="submit">
                  Queue controlled {dashboard.next_operation} run
                </button>
                <p className="form-help">
                  The model cannot report success. A project version is
                  persisted only after the controlled builder computes every
                  passing result.
                </p>
              </form>
            )}
          </section>

          <section className="panel">
            <p className="eyebrow">CURRENT PROJECT</p>
            <h2>{current ? `Version ${current.version}` : "Not built yet"}</h2>
            {current ? (
              <>
                <div className="agent-contract-grid">
                  <div>
                    <span>Specification</span>
                    <strong>
                      v{current.source_website_specification_version} /{" "}
                      {current.source_is_current ? "current" : "stale"}
                    </strong>
                  </div>
                  <div>
                    <span>Build</span>
                    <strong>{String(current.build_report.status)}</strong>
                  </div>
                  <div>
                    <span>Checks</span>
                    <strong>{String(current.check_report.status)}</strong>
                  </div>
                  <div>
                    <span>Dependencies</span>
                    <strong>
                      {String(current.dependency_manifest.manager)}
                    </strong>
                  </div>
                </div>
                <p className="fine-print">
                  Source <code>{current.source_digest}</code>
                  <br />
                  Build <code>{current.build_digest}</code>
                </p>
                <details>
                  <summary>Inspect source files</summary>
                  {current.source_files.map((file) => (
                    <article className="panel" key={String(file.path)}>
                      <h3>{String(file.path)}</h3>
                      <p className="fine-print">
                        {String(file.media_type)} / {String(file.size_bytes)}{" "}
                        bytes / <code>{String(file.sha256)}</code>
                      </p>
                      <pre className="context-preview">
                        {String(file.content)}
                      </pre>
                    </article>
                  ))}
                </details>
                <details>
                  <summary>Inspect computed checks and tool audit</summary>
                  <pre className="context-preview">
                    {JSON.stringify(current.check_report, null, 2)}
                  </pre>
                  <pre className="context-preview">
                    {JSON.stringify(current.tool_audit, null, 2)}
                  </pre>
                </details>
              </>
            ) : (
              <p className="fine-print">
                No source tree or successful build is being claimed.
              </p>
            )}
          </section>

          <section className="panel">
            <p className="eyebrow">RUNS</p>
            <h2>Website coding activity</h2>
            {dashboard.recent_runs.length ? (
              <ul>
                {dashboard.recent_runs.map((run) => (
                  <li key={run.id}>
                    {timestamp(run.created_at)} UTC —{" "}
                    {run.error_type ?? run.status}{" "}
                    <Link className="text-link" href={`/agents?run=${run.id}`}>
                      Inspect
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="fine-print">No coding run has been queued.</p>
            )}
          </section>

          <section className="panel">
            <p className="eyebrow">IMMUTABLE HISTORY</p>
            <h2>Project versions</h2>
            {dashboard.history.length ? (
              <ul>
                {dashboard.history.map((project) => (
                  <li key={project.id}>
                    v{project.version} — {project.operation} — {project.status}{" "}
                    — {timestamp(project.created_at)} UTC — build{" "}
                    <code>{project.build_digest}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="fine-print">No project version exists.</p>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
