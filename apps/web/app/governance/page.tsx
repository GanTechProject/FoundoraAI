import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { getGovernanceDashboard } from "../../lib/governance";
import {
  authorizeGovernanceAction,
  decideGovernanceApproval,
  evaluateGovernanceAction,
  logout,
  updateGovernanceKillSwitch,
  updateGovernanceSettings,
  updateGovernanceToolPermission,
} from "../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  conflict: "Governance state changed. Reload and try again.",
  denied: "The live policy denied that authorization.",
  invalid: "The proposed action or control values are invalid.",
  "not-found": "The selected-business governance record was not found.",
  unavailable: "Governance state is temporarily unavailable.",
};

const updates: Record<string, string> = {
  approved:
    "The approval was recorded. Execution still requires a live recheck.",
  authorized: "The approved action passed its execution-time policy recheck.",
  evaluated: "The proposed action was classified and evaluated durably.",
  killed: "The global kill switch is engaged across all businesses.",
  rejected: "The approval was rejected and cannot authorize execution.",
  released: "The global kill switch was released.",
  settings: "Selected-business autonomy and spend controls were updated.",
  tool: "Selected-business tool permission was updated.",
};

function timestamp(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value));
}

export default async function GovernancePage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; updated?: string; action?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const params = await searchParams;
  const dashboard = await getGovernanceDashboard();
  const selected = dashboard?.actions.find((item) => item.id === params.action);

  return (
    <main className="settings-shell tasks-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / GOVERNANCE</p>
          <h1>Policy, risk, approvals, and hard stops</h1>
          <p className="lede">
            Every proposed action is classified from a code-reviewed catalog,
            pinned to an immutable policy version, and checked again immediately
            before authorization. Approval is evidence, never a bypass.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Business workspace
          </Link>
          <Link className="text-link" href="/workflows">
            Workflow engine
          </Link>
          <Link className="text-link" href="/tasks">
            Task engine
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
          Governance state could not be loaded. No policy state is being
          assumed.
        </p>
      ) : null}

      {dashboard ? (
        <>
          <section className="panel" aria-labelledby="kill-switch-heading">
            <div className="agent-card__heading">
              <div>
                <p className="eyebrow">GLOBAL CONTROL</p>
                <h2 id="kill-switch-heading">Global kill switch</h2>
              </div>
              <span
                className={`status-pill status-pill--${dashboard.controls.kill_switch_enabled ? "failed" : "active"}`}
              >
                {dashboard.controls.kill_switch_enabled
                  ? "ENGAGED"
                  : "RELEASED"}
              </span>
            </div>
            <p>
              This control is checked beneath workflow prompts immediately
              before governed execution. Revision {dashboard.controls.revision}.
            </p>
            {dashboard.controls.kill_switch_enabled ? (
              <form
                className="run-actions"
                action={updateGovernanceKillSwitch.bind(null, false)}
              >
                <input
                  type="hidden"
                  name="revision"
                  value={dashboard.controls.revision}
                />
                <button type="submit">Release kill switch</button>
              </form>
            ) : (
              <form
                className="agent-run-form"
                action={updateGovernanceKillSwitch.bind(null, true)}
              >
                <input
                  type="hidden"
                  name="revision"
                  value={dashboard.controls.revision}
                />
                <label htmlFor="kill-reason">Required safety reason</label>
                <input
                  id="kill-reason"
                  name="reason"
                  maxLength={500}
                  required
                />
                <button type="submit">Engage global kill switch</button>
              </form>
            )}
          </section>

          <section className="panel" aria-labelledby="policy-heading">
            <p className="eyebrow">IMMUTABLE POLICY</p>
            <h2 id="policy-heading">
              {dashboard.policy.display_name}@{dashboard.policy.version}
            </h2>
            <p>{dashboard.policy.description}</p>
            <p className="fine-print">
              R3/R4 always require owner approval. R5 is prohibited. Unknown
              tools are denied. Restricted data cannot cross an external-action
              boundary.
            </p>
          </section>

          <section className="panel" aria-labelledby="controls-heading">
            <p className="eyebrow">SELECTED-BUSINESS CONTROLS</p>
            <h2 id="controls-heading">Autonomy and spend ceilings</h2>
            <p>
              Authorized today:{" "}
              {dashboard.settings.authorized_spend_today_microusd} micro-USD.
              Zero remains the safe default and blocks spend.
            </p>
            <form className="agent-run-form" action={updateGovernanceSettings}>
              <input
                type="hidden"
                name="revision"
                value={dashboard.settings.revision}
              />
              <label htmlFor="autonomy-level">Autonomy level</label>
              <select
                id="autonomy-level"
                name="autonomy_level"
                defaultValue={dashboard.settings.autonomy_level}
              >
                <option value="OFF">OFF</option>
                <option value="RECOMMEND">RECOMMEND</option>
                <option value="ASSISTED">ASSISTED</option>
                <option value="AUTONOMOUS_LOW_RISK">AUTONOMOUS_LOW_RISK</option>
              </select>
              <label htmlFor="daily-spend">Daily spend limit (micro-USD)</label>
              <input
                id="daily-spend"
                name="daily_spend_limit_microusd"
                type="number"
                min="0"
                defaultValue={dashboard.settings.daily_spend_limit_microusd}
                required
              />
              <label htmlFor="action-spend">
                Per-action spend limit (micro-USD)
              </label>
              <input
                id="action-spend"
                name="per_action_spend_limit_microusd"
                type="number"
                min="0"
                defaultValue={
                  dashboard.settings.per_action_spend_limit_microusd
                }
                required
              />
              <button type="submit">Save governance controls</button>
            </form>
          </section>

          <section className="panel" aria-labelledby="proposal-heading">
            <p className="eyebrow">POLICY EVALUATION</p>
            <h2 id="proposal-heading">Propose an authorization</h2>
            <p>
              This records and evaluates authority only. It does not call a
              provider or claim an external side effect occurred.
            </p>
            <form className="agent-run-form" action={evaluateGovernanceAction}>
              <label htmlFor="action-type">Action</label>
              <select id="action-type" name="action_type">
                {dashboard.action_catalog.map((item) => (
                  <option key={item.action_type} value={item.action_type}>
                    {item.risk_class} â€” {item.display_name}
                  </option>
                ))}
              </select>
              <label htmlFor="execution-mode">Execution mode</label>
              <select id="execution-mode" name="execution_mode">
                <option value="manual">Manual</option>
                <option value="autonomous">Autonomous</option>
              </select>
              <label htmlFor="data-classification">Data classification</label>
              <select id="data-classification" name="data_classification">
                <option value="internal">Internal</option>
                <option value="public">Public</option>
                <option value="confidential">Confidential</option>
                <option value="restricted">Restricted</option>
              </select>
              <label htmlFor="proposed-tool">Optional code-reviewed tool</label>
              <select id="proposed-tool" name="tool_id" defaultValue="">
                <option value="">No tool</option>
                {dashboard.tool_permissions.map((item) => (
                  <option key={item.tool_id} value={item.tool_id}>
                    {item.tool_id}
                  </option>
                ))}
              </select>
              <label htmlFor="proposed-spend">
                Requested spend (micro-USD)
              </label>
              <input
                id="proposed-spend"
                name="requested_spend_microusd"
                type="number"
                min="0"
                defaultValue="0"
                required
              />
              <label htmlFor="proposal-target">Optional target</label>
              <input id="proposal-target" name="target" maxLength={300} />
              <input type="hidden" name="frequency_key" value="owner-ui" />
              <button type="submit">Classify and evaluate</button>
            </form>
          </section>

          <section className="panel" aria-labelledby="tools-heading">
            <p className="eyebrow">LEAST AUTHORITY</p>
            <h2 id="tools-heading">Tool permissions</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Tool</th>
                    <th>Risk</th>
                    <th>Scope</th>
                    <th>State</th>
                    <th>Control</th>
                  </tr>
                </thead>
                <tbody>
                  {dashboard.tool_permissions.map((tool) => (
                    <tr key={tool.tool_id}>
                      <td>
                        <code>{tool.tool_id}</code>
                      </td>
                      <td>{tool.risk_class}</td>
                      <td>{tool.internal ? "internal" : "external"}</td>
                      <td>{tool.enabled ? "enabled" : "disabled"}</td>
                      <td>
                        <form
                          action={updateGovernanceToolPermission.bind(
                            null,
                            tool.tool_id,
                            !tool.enabled,
                            tool.revision,
                          )}
                        >
                          <button className="button-secondary" type="submit">
                            {tool.enabled ? "Disable" : "Enable"}
                          </button>
                        </form>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel" aria-labelledby="actions-heading">
            <p className="eyebrow">DURABLE AUTHORIZATION LEDGER</p>
            <h2 id="actions-heading">Actions and approvals</h2>
            {dashboard.actions.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Action</th>
                      <th>Risk</th>
                      <th>Status</th>
                      <th>Target</th>
                      <th>Decision</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dashboard.actions.map((action) => (
                      <tr key={action.id}>
                        <td>
                          <Link
                            className="text-link"
                            href={`/governance?action=${action.id}`}
                          >
                            {action.action_type}
                          </Link>
                        </td>
                        <td>{action.risk_class}</td>
                        <td>{action.status}</td>
                        <td>{action.target ?? "-"}</td>
                        <td>
                          {action.approval?.status === "pending" ? (
                            <div className="run-actions">
                              <form
                                action={decideGovernanceApproval.bind(
                                  null,
                                  action.approval.id,
                                  "approved",
                                )}
                              >
                                <input
                                  type="hidden"
                                  name="reason"
                                  value="Approved in owner governance console"
                                />
                                <button type="submit">Approve</button>
                              </form>
                              <form
                                action={decideGovernanceApproval.bind(
                                  null,
                                  action.approval.id,
                                  "rejected",
                                )}
                              >
                                <input
                                  type="hidden"
                                  name="reason"
                                  value="Rejected in owner governance console"
                                />
                                <button
                                  className="button-secondary"
                                  type="submit"
                                >
                                  Reject
                                </button>
                              </form>
                            </div>
                          ) : action.status === "approved" ? (
                            <form
                              action={authorizeGovernanceAction.bind(
                                null,
                                action.id,
                              )}
                            >
                              <button type="submit">
                                Recheck authorization
                              </button>
                            </form>
                          ) : (
                            (action.approval?.status ?? "-")
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="fine-print">
                No governed action has been proposed.
              </p>
            )}
          </section>

          {selected ? (
            <section
              className="panel"
              aria-labelledby="selected-action-heading"
            >
              <p className="eyebrow">ACTION EVIDENCE</p>
              <h2 id="selected-action-heading">{selected.action_type}</h2>
              <code>{selected.id}</code>
              <p>{selected.rationale}</p>
              <dl className="detail-grid">
                <div>
                  <dt>Risk / mode</dt>
                  <dd>
                    {selected.risk_class} / {selected.execution_mode}
                  </dd>
                </div>
                <div>
                  <dt>Classification</dt>
                  <dd>{selected.data_classification}</dd>
                </div>
                <div>
                  <dt>Spend requested</dt>
                  <dd>{selected.requested_spend_microusd} micro-USD</dd>
                </div>
                <div>
                  <dt>Authorized</dt>
                  <dd>{timestamp(selected.authorized_at)} UTC</dd>
                </div>
              </dl>
            </section>
          ) : null}

          <section className="panel" aria-labelledby="audit-heading">
            <p className="eyebrow">APPEND-ONLY EVIDENCE</p>
            <h2 id="audit-heading">Governance audit trail</h2>
            <ol className="event-list">
              {dashboard.audit_events.map((event) => (
                <li key={event.id}>
                  <strong>{event.event_type}</strong>
                  {event.action_id ? ` â€” ${event.action_id}` : " â€” global"}
                  <span>{timestamp(event.created_at)} UTC</span>
                </li>
              ))}
            </ol>
          </section>
        </>
      ) : null}
    </main>
  );
}
