import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { getWorkflowDashboard, getWorkflowRun } from "../../lib/workflows";
import {
  cancelWorkflow,
  logout,
  resumeWorkflow,
  startWorkflow,
} from "../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  conflict: "The workflow is not at a checkpoint that accepts that command.",
  invalid: "The workflow input does not match the pinned version schema.",
  "not-found":
    "The workflow, run, or linked task was not found in this business.",
  unavailable: "The durable workflow coordinator is temporarily unavailable.",
};

const updates: Record<string, string> = {
  queued:
    "The pinned workflow run and all step records were persisted and queued.",
  resumed:
    "The checkpoint command was persisted idempotently and execution resumed.",
  cancelled: "The workflow and unfinished steps were cancelled durably.",
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

export default async function WorkflowsPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; updated?: string; run?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const params = await searchParams;
  const dashboard = await getWorkflowDashboard();
  const selected = params.run ? await getWorkflowRun(params.run) : null;

  return (
    <main className="settings-shell tasks-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / WORKFLOW ENGINE</p>
          <h1>Versioned execution, durable checkpoints</h1>
          <p className="lede">
            A workflow is a reusable execution graph; a task is a unit of work.
            Runs pin an immutable graph and persist every dependency, retry,
            wait, owner checkpoint, failure, and compensation transition.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Business workspace
          </Link>
          <Link className="text-link" href="/tasks">
            Task engine
          </Link>
          <Link className="text-link" href="/governance">
            Governance
          </Link>
          <Link className="text-link" href="/events">
            Events
          </Link>
          <Link className="text-link" href="/knowledge">
            Knowledge
          </Link>
          <Link className="text-link" href="/agents">
            Agents &amp; skills
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
          Workflow state could not be loaded. No execution state is being
          assumed.
        </p>
      ) : null}

      {dashboard ? (
        <>
          <section
            className="agent-registry"
            aria-labelledby="definitions-heading"
          >
            <div className="section-heading">
              <p className="eyebrow">IMMUTABLE REGISTRY</p>
              <h2 id="definitions-heading">Current workflow versions</h2>
            </div>
            {dashboard.definitions.map((definition) => (
              <article className="panel agent-card" key={definition.version_id}>
                <div className="agent-card__heading">
                  <div>
                    <h3>{definition.display_name}</h3>
                    <code>
                      {definition.workflow_id}@{definition.version}
                    </code>
                  </div>
                  <span className="status-pill status-pill--active">
                    R0 / manual start
                  </span>
                </div>
                <p>{definition.description}</p>
                <ol className="event-list">
                  {definition.steps.map((step) => (
                    <li key={step.key}>
                      <strong>{step.key}</strong> — {step.type}; depends on{" "}
                      {step.depends_on.join(", ") || "nothing"}; retries{" "}
                      {step.max_retries}
                    </li>
                  ))}
                </ol>
                <form className="agent-run-form" action={startWorkflow}>
                  <input
                    type="hidden"
                    name="workflow_id"
                    value={definition.workflow_id}
                  />
                  <label htmlFor={`workflow-input-${definition.workflow_id}`}>
                    Schema-bound run input (JSON)
                  </label>
                  <textarea
                    id={`workflow-input-${definition.workflow_id}`}
                    name="input"
                    defaultValue={
                      '{"message":"Phase 10 verification","include_branch":true}'
                    }
                    rows={4}
                    required
                  />
                  <label htmlFor={`workflow-task-${definition.workflow_id}`}>
                    Optional selected-business task ID
                  </label>
                  <input
                    id={`workflow-task-${definition.workflow_id}`}
                    name="task_id"
                  />
                  <button type="submit" disabled={!definition.enabled}>
                    Start pinned workflow
                  </button>
                </form>
              </article>
            ))}
          </section>

          <section className="panel" aria-labelledby="runs-heading">
            <p className="eyebrow">SELECTED-BUSINESS RUNS</p>
            <h2 id="runs-heading">Durable execution ledger</h2>
            {dashboard.runs.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Workflow</th>
                      <th>Status</th>
                      <th>Current step</th>
                      <th>Created</th>
                      <th>Inspect</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dashboard.runs.map((run) => (
                      <tr key={run.id}>
                        <td>
                          {run.workflow_id}@{run.workflow_version}
                        </td>
                        <td>{run.status}</td>
                        <td>{run.current_step_key ?? "-"}</td>
                        <td>{timestamp(run.created_at)} UTC</td>
                        <td>
                          <Link
                            className="text-link"
                            href={`/workflows?run=${run.id}`}
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
                No workflow has run for this business.
              </p>
            )}
          </section>

          {selected ? (
            <section
              className="panel task-inspector"
              aria-labelledby="run-heading"
            >
              <div className="agent-card__heading">
                <div>
                  <p className="eyebrow">WORKFLOW RUN</p>
                  <h2 id="run-heading">
                    {selected.workflow_id}@{selected.workflow_version}
                  </h2>
                  <code>{selected.id}</code>
                </div>
                <span className={`status-pill status-pill--${selected.status}`}>
                  {selected.status}
                </span>
              </div>
              {selected.error_message ? (
                <p className="notice notice--error">
                  {selected.error_type}: {selected.error_message}
                </p>
              ) : null}
              <div className="run-actions">
                <Link
                  className="button-secondary"
                  href={`/workflows?run=${selected.id}`}
                >
                  Refresh durable state
                </Link>
                {selected.status === "waiting_approval" ? (
                  <>
                    <form
                      action={resumeWorkflow.bind(
                        null,
                        selected.id,
                        "approved",
                      )}
                    >
                      <button type="submit">Approve R0 checkpoint</button>
                    </form>
                    <form
                      action={resumeWorkflow.bind(
                        null,
                        selected.id,
                        "rejected",
                      )}
                    >
                      <button className="button-secondary" type="submit">
                        Reject checkpoint
                      </button>
                    </form>
                  </>
                ) : null}
                {selected.status === "waiting" ||
                selected.status === "waiting_agent" ? (
                  <form action={resumeWorkflow.bind(null, selected.id, null)}>
                    <button type="submit">
                      {selected.status === "waiting_agent"
                        ? "Collect terminal agent result"
                        : "Resume after wait"}
                    </button>
                  </form>
                ) : null}
                {!terminal.has(selected.status) ? (
                  <form action={cancelWorkflow.bind(null, selected.id)}>
                    <button className="button-secondary" type="submit">
                      Cancel run
                    </button>
                  </form>
                ) : null}
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Step</th>
                      <th>Type</th>
                      <th>Status</th>
                      <th>Attempts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selected.steps.map((step) => (
                      <tr key={step.id}>
                        <td>{step.sequence}</td>
                        <td>{step.key}</td>
                        <td>{step.type}</td>
                        <td>{step.status}</td>
                        <td>
                          {step.attempt_count}/{step.max_retries + 1}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <h3>Append-only run events</h3>
              <ol className="event-list">
                {selected.events.map((event) => (
                  <li key={event.id}>
                    <strong>
                      {event.sequence}. {event.event_type}
                    </strong>
                    {event.step_key ? ` — ${event.step_key}` : ""}
                    <span>{timestamp(event.created_at)} UTC</span>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
