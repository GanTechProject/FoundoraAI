import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { getTask, getTaskDashboard, type TaskStatus } from "../../lib/tasks";
import {
  addTaskDependency,
  createTask,
  logout,
  retryTask,
  transitionTask,
} from "../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  conflict:
    "The requested lifecycle or dependency change conflicts with current task state. Complete blockers and refresh before trying again.",
  invalid: "The task data is incomplete or invalid.",
  "not-found": "The task, goal, or agent owner was not found in this business.",
  unavailable: "The task engine is temporarily unavailable.",
};

const updates: Record<string, string> = {
  created: "The draft task and its creation event were persisted.",
  dependency: "The acyclic dependency was persisted.",
  transitioned: "The lifecycle transition and event were persisted atomically.",
  retried: "The failed task was safely advanced to its next queued retry.",
};

const nextStates: Record<TaskStatus, TaskStatus[]> = {
  draft: ["planned", "cancelled"],
  planned: ["queued", "blocked", "cancelled"],
  queued: ["running", "blocked", "cancelled"],
  running: ["blocked", "waiting_approval", "completed", "failed", "cancelled"],
  blocked: ["planned", "queued", "cancelled"],
  waiting_approval: ["queued", "running", "failed", "cancelled"],
  completed: [],
  failed: ["cancelled"],
  cancelled: [],
};

function timestamp(value: string | null): string {
  if (!value) return "No due date";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

export default async function TasksPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; updated?: string; task?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const params = await searchParams;
  const dashboard = await getTaskDashboard();
  const selected = params.task ? await getTask(params.task) : null;

  return (
    <main className="settings-shell tasks-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / TASK ENGINE</p>
          <h1>Durable work, explicit dependencies</h1>
          <p className="lede">
            Goals provide direction; tasks hold execution state. Queue and run
            transitions are rejected until every dependency is complete, and
            each accepted change is recorded as an inspectable event.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Business workspace
          </Link>
          <Link className="text-link" href="/agents">
            Agents &amp; skills
          </Link>
          <Link className="text-link" href="/brain">
            Business brain
          </Link>
          <Link className="text-link" href="/workflows">
            Workflows
          </Link>
          <Link className="text-link" href="/governance">
            Governance
          </Link>
          <Link className="text-link" href="/events">
            Events
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
          Task state could not be loaded. No lifecycle state is being assumed.
        </p>
      ) : null}

      {dashboard ? (
        <>
          <section className="panel" aria-labelledby="create-task-heading">
            <p className="eyebrow">NEW DURABLE TASK</p>
            <h2 id="create-task-heading">Start in draft</h2>
            <form className="workspace-form task-form" action={createTask}>
              <label htmlFor="task-title">Title</label>
              <input
                id="task-title"
                name="title"
                minLength={1}
                maxLength={200}
                required
              />
              <label htmlFor="task-description">Description</label>
              <textarea
                id="task-description"
                name="description"
                maxLength={4000}
                rows={3}
              />
              <div className="settings-grid">
                <label>
                  Goal
                  <select name="goal_id" defaultValue="">
                    <option value="">No linked goal</option>
                    {dashboard.goals.map((goal) => (
                      <option key={goal.id} value={goal.id}>
                        {goal.title} ({goal.status})
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Priority
                  <select name="priority" defaultValue="3">
                    <option value="1">1 — urgent</option>
                    <option value="2">2 — high</option>
                    <option value="3">3 — normal</option>
                    <option value="4">4 — low</option>
                    <option value="5">5 — someday</option>
                  </select>
                </label>
                <label>
                  Owner
                  <select name="owner" defaultValue="founder">
                    <option value="unassigned">Unassigned</option>
                    <option value="founder">Founder</option>
                    {dashboard.agent_owners.map((owner) => (
                      <option
                        key={owner.agent_id}
                        value={`agent:${owner.agent_id}`}
                      >
                        {owner.display_name}@{owner.version}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Due at (UTC)
                  <input name="due_at" type="datetime-local" />
                </label>
                <label>
                  Maximum safe retries
                  <input
                    name="max_retries"
                    type="number"
                    min="0"
                    max="10"
                    defaultValue="0"
                  />
                </label>
              </div>
              <button type="submit">Persist draft task</button>
            </form>
          </section>

          <section className="panel" aria-labelledby="task-ledger-heading">
            <p className="eyebrow">SELECTED-BUSINESS LEDGER</p>
            <h2 id="task-ledger-heading">Tasks by priority and due date</h2>
            <p className="fine-print">
              Showing {dashboard.tasks.length} of {dashboard.total_tasks} tasks.
            </p>
            {dashboard.tasks.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Priority</th>
                      <th>Task</th>
                      <th>Owner</th>
                      <th>Status</th>
                      <th>Dependencies</th>
                      <th>Due</th>
                      <th>Inspect</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dashboard.tasks.map((task) => (
                      <tr key={task.id}>
                        <td>P{task.priority}</td>
                        <td>{task.title}</td>
                        <td>
                          {task.owner_agent_id
                            ? `${task.owner_agent_id}@${task.owner_agent_version ?? "pinned"}`
                            : task.owner_type}
                        </td>
                        <td>{task.status}</td>
                        <td>
                          {task.dependencies.length
                            ? `${task.dependencies.length - task.blocked_by.length}/${task.dependencies.length} complete`
                            : "None"}
                        </td>
                        <td>{timestamp(task.due_at)} UTC</td>
                        <td>
                          <Link
                            className="text-link"
                            href={`/tasks?task=${task.id}`}
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
                No task has been recorded for this business.
              </p>
            )}
          </section>

          {selected ? (
            <section
              className="panel task-inspector"
              aria-labelledby="task-heading"
            >
              <div className="agent-card__heading">
                <div>
                  <p className="eyebrow">TASK INSPECTOR</p>
                  <h2 id="task-heading">{selected.title}</h2>
                  <code>{selected.id}</code>
                </div>
                <span className={`status-pill status-pill--${selected.status}`}>
                  {selected.status}
                </span>
              </div>
              <p>{selected.description ?? "No description supplied."}</p>
              <div className="agent-contract-grid">
                <div>
                  <span>Retry budget</span>
                  <strong>
                    {selected.retry_count}/{selected.max_retries}
                  </strong>
                </div>
                <div>
                  <span>Due</span>
                  <strong>{timestamp(selected.due_at)} UTC</strong>
                </div>
                <div>
                  <span>Goal</span>
                  <strong>{selected.goal_id ?? "Unlinked"}</strong>
                </div>
              </div>
              {selected.last_error ? (
                <p className="notice notice--error">{selected.last_error}</p>
              ) : null}

              {selected.status === "draft" ||
              selected.status === "planned" ||
              selected.status === "blocked" ? (
                <form
                  className="workspace-form"
                  action={addTaskDependency.bind(null, selected.id)}
                >
                  <label htmlFor="depends-on">Add dependency</label>
                  <select id="depends-on" name="depends_on_task_id" required>
                    <option value="">Choose a task</option>
                    {dashboard.tasks
                      .filter((task) => task.id !== selected.id)
                      .map((task) => (
                        <option key={task.id} value={task.id}>
                          {task.title} ({task.status})
                        </option>
                      ))}
                  </select>
                  <button type="submit">Add acyclic dependency</button>
                </form>
              ) : null}

              {nextStates[selected.status].length ? (
                <form
                  className="workspace-form"
                  action={transitionTask.bind(null, selected.id)}
                >
                  <label htmlFor="next-status">Next valid state</label>
                  <select id="next-status" name="status" required>
                    {nextStates[selected.status].map((state) => (
                      <option key={state} value={state}>
                        {state}
                      </option>
                    ))}
                  </select>
                  <label htmlFor="task-error">
                    Failure detail (when failing)
                  </label>
                  <input id="task-error" name="error" maxLength={500} />
                  <button type="submit">Persist transition</button>
                </form>
              ) : null}

              {selected.status === "failed" &&
              selected.retry_count < selected.max_retries ? (
                <form action={retryTask.bind(null, selected.id)}>
                  <button type="submit">Retry safely</button>
                </form>
              ) : null}

              <div className="settings-grid task-detail-grid">
                <article>
                  <h3>Dependencies</h3>
                  {selected.dependencies.length ? (
                    <ul>
                      {selected.dependencies.map((dependency) => (
                        <li key={dependency.task_id}>
                          {dependency.satisfied ? "✓" : "○"} {dependency.title}{" "}
                          — {dependency.status}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="fine-print">No dependencies.</p>
                  )}
                </article>
                <article>
                  <h3>Append-only events</h3>
                  <ol className="event-list">
                    {selected.events.map((event) => (
                      <li key={event.id}>
                        <strong>{event.event_type}</strong>{" "}
                        {event.from_status ?? "∅"} → {event.to_status ?? "∅"}
                        <span>{timestamp(event.created_at)} UTC</span>
                      </li>
                    ))}
                  </ol>
                </article>
              </div>
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
