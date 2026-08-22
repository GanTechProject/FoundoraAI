import Link from "next/link";
import { redirect } from "next/navigation";

import { getAgentDashboard, getAgentRun } from "../../lib/agents";
import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { cancelAgentRun, logout, runAgent } from "../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  agent: "The selected agent definition is disabled or unavailable.",
  invalid: "The objective must contain between 1 and 500 characters.",
  terminal:
    "That run already reached a terminal state and cannot be cancelled.",
  unavailable: "The agent runtime is temporarily unavailable.",
};

const updates: Record<string, string> = {
  cancelled:
    "Cancellation was persisted. Any late provider output will be discarded.",
  queued: "The run was persisted and queued for the background worker.",
};

const terminal = new Set(["completed", "failed", "cancelled"]);

function timestamp(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value));
}

function usd(microusd: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 6,
  }).format(microusd / 1_000_000);
}

export default async function AgentsPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; updated?: string; run?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const params = await searchParams;
  const dashboard = await getAgentDashboard();
  const selectedRun = params.run ? await getAgentRun(params.run) : null;

  return (
    <main className="settings-shell agents-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / AGENT RUNTIME</p>
          <h1>Versioned, inspectable execution</h1>
          <p className="lede">
            Every run is pinned to an immutable contract, scoped to the selected
            business, executed by the worker, and linked to its actual model
            usage. This phase permits no tools or external side effects.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Business workspace
          </Link>
          <Link className="text-link" href="/brain">
            Business brain
          </Link>
          <Link className="text-link" href="/settings/ai">
            AI gateway
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
      {!dashboard ? (
        <p className="notice notice--error" role="alert">
          Registry state could not be loaded. No agent capability is being
          assumed.
        </p>
      ) : null}

      {dashboard ? (
        <>
          <section
            className="agent-registry"
            aria-labelledby="registry-heading"
          >
            <div className="section-heading">
              <p className="eyebrow">REGISTRY</p>
              <h2 id="registry-heading">Current definitions</h2>
            </div>
            {dashboard.definitions.map((definition) => (
              <article className="panel agent-card" key={definition.agent_id}>
                <div className="agent-card__heading">
                  <div>
                    <h3>{definition.display_name}</h3>
                    <code>
                      {definition.agent_id}@{definition.version}
                    </code>
                  </div>
                  <span className="status-pill status-pill--active">
                    {definition.risk_level} / {definition.maximum_autonomy}
                  </span>
                </div>
                <p>{definition.purpose}</p>
                <div className="agent-contract-grid">
                  <div>
                    <span>Role</span>
                    <strong>{definition.role}</strong>
                  </div>
                  <div>
                    <span>Skills</span>
                    <strong>
                      {definition.allowed_skills.length
                        ? definition.allowed_skills.join(", ")
                        : "None (Phase 08)"}
                    </strong>
                  </div>
                  <div>
                    <span>Tools</span>
                    <strong>
                      {definition.allowed_tools.length
                        ? definition.allowed_tools.join(", ")
                        : "None"}
                    </strong>
                  </div>
                </div>
                <details>
                  <summary>Inspect permissions and boundaries</summary>
                  <div className="agent-boundaries">
                    <div>
                      <h4>Responsibilities</h4>
                      <ul>
                        {definition.responsibilities.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <h4>Forbidden</h4>
                      <ul>
                        {definition.forbidden_actions.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </details>
                <form className="agent-run-form" action={runAgent}>
                  <input
                    type="hidden"
                    name="agent_id"
                    value={definition.agent_id}
                  />
                  <label htmlFor={`objective-${definition.agent_id}`}>
                    Read-only objective
                  </label>
                  <textarea
                    id={`objective-${definition.agent_id}`}
                    name="objective"
                    defaultValue="Inspect the selected business context and identify its most important grounded observation."
                    minLength={1}
                    maxLength={500}
                    rows={3}
                    required
                  />
                  <button type="submit" disabled={!definition.enabled}>
                    Queue manual R0 run
                  </button>
                </form>
              </article>
            ))}
          </section>

          {selectedRun ? (
            <section
              className="panel agent-inspector"
              aria-labelledby="run-heading"
            >
              <div className="agent-card__heading">
                <div>
                  <p className="eyebrow">RUN INSPECTOR</p>
                  <h2 id="run-heading">{selectedRun.id}</h2>
                </div>
                <span
                  className={`status-pill status-pill--${selectedRun.status}`}
                >
                  {selectedRun.status}
                </span>
              </div>
              <div className="agent-contract-grid">
                <div>
                  <span>Agent version</span>
                  <strong>
                    {selectedRun.agent_id}@{selectedRun.agent_version}
                  </strong>
                </div>
                <div>
                  <span>Queued</span>
                  <strong>{timestamp(selectedRun.queued_at)} UTC</strong>
                </div>
                <div>
                  <span>Completed</span>
                  <strong>{timestamp(selectedRun.completed_at)} UTC</strong>
                </div>
                <div>
                  <span>Usage linkage</span>
                  <strong>
                    {selectedRun.usage.calls} attempt(s) /{" "}
                    {selectedRun.usage.total_tokens} tokens /{" "}
                    {usd(selectedRun.usage.estimated_cost_microusd)}
                  </strong>
                </div>
              </div>
              {selectedRun.error_type ? (
                <p className="notice notice--error">
                  {selectedRun.error_type}: {selectedRun.error_message}
                </p>
              ) : null}
              {!terminal.has(selectedRun.status) ? (
                <div className="run-actions">
                  <Link
                    className="button-secondary"
                    href={`/agents?run=${selectedRun.id}`}
                  >
                    Refresh run
                  </Link>
                  <form action={cancelAgentRun.bind(null, selectedRun.id)}>
                    <button className="button-danger" type="submit">
                      Cancel run
                    </button>
                  </form>
                </div>
              ) : null}
              <div className="settings-grid">
                <article>
                  <h3>Structured input</h3>
                  <pre className="context-preview">
                    {JSON.stringify(selectedRun.structured_input, null, 2)}
                  </pre>
                </article>
                <article>
                  <h3>Structured output</h3>
                  <pre className="context-preview">
                    {selectedRun.structured_output
                      ? JSON.stringify(selectedRun.structured_output, null, 2)
                      : "No valid output has been persisted."}
                  </pre>
                </article>
              </div>
              {selectedRun.usage.attempts.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Attempt</th>
                        <th>Provider / model</th>
                        <th>Status</th>
                        <th>Tokens</th>
                        <th>Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedRun.usage.attempts.map((attempt) => (
                        <tr
                          key={`${attempt.operation_id}-${attempt.attempt_number}`}
                        >
                          <td>{attempt.attempt_number}</td>
                          <td>
                            {attempt.provider}/{attempt.model}
                          </td>
                          <td>{attempt.error_type ?? attempt.status}</td>
                          <td>
                            {attempt.input_tokens + attempt.output_tokens}
                          </td>
                          <td>{usd(attempt.estimated_cost_microusd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </section>
          ) : null}

          <section className="panel" aria-labelledby="runs-heading">
            <p className="eyebrow">DURABLE LIFECYCLE</p>
            <h2 id="runs-heading">Recent selected-business runs</h2>
            {dashboard.runs.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Created</th>
                      <th>Agent</th>
                      <th>Status</th>
                      <th>Usage</th>
                      <th>Inspect</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dashboard.runs.map((run) => (
                      <tr key={run.id}>
                        <td>{timestamp(run.created_at)} UTC</td>
                        <td>
                          {run.agent_id}@{run.agent_version}
                        </td>
                        <td>{run.error_type ?? run.status}</td>
                        <td>{run.usage.total_tokens} tokens</td>
                        <td>
                          <Link
                            className="text-link"
                            href={`/agents?run=${run.id}`}
                          >
                            Inspect
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="fine-print">
                No agent run has been recorded for this business.
              </p>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
