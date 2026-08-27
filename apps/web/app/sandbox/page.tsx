import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import {
  getSandboxExecution,
  getSandboxExecutions,
  type SandboxExecutionDetail,
  type SandboxExecutionStatus,
} from "../../lib/sandbox";
import {
  cancelSandboxExecution,
  logout,
  requestSandboxExecution,
  startSandboxExecution,
} from "../actions";

export const dynamic = "force-dynamic";

const terminalStatuses = new Set<SandboxExecutionStatus>([
  "rejected",
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
  "resource_exhausted",
  "infrastructure_failed",
  "cleanup_failed",
]);

const errors: Record<string, string> = {
  conflict: "The sandbox execution state changed. Reload and try again.",
  denied: "Live governance controls denied this sandbox operation.",
  invalid:
    "The active project, specification, profile, or pinned evidence is not ready for sandbox execution.",
  "not-found": "That execution does not belong to the selected business.",
  queue:
    "The execution remains durable, but queue delivery is temporarily unavailable.",
  session: "The owner session expired. Sign in again.",
  unavailable: "Sandbox state is temporarily unavailable.",
};

const updates: Record<string, string> = {
  cancelled:
    "Cancellation was requested. The worker will persist cleanup proof before terminal state.",
  queued: "The approved execution was queued for isolated execution.",
  requested:
    "The exact project and profile were pinned. Explicit R2 approval is required before start.",
};

function timestamp(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value));
}

function Evidence({ title, value }: { title: string; value: unknown }) {
  if (value === null || value === undefined) return null;
  return (
    <div>
      <h3>{title}</h3>
      <pre className="context-preview">
        {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function ExecutionActions({
  execution,
}: {
  execution: SandboxExecutionDetail;
}) {
  const canStart =
    execution.status === "waiting_approval" &&
    ["approved", "authorized"].includes(execution.governance_status);
  const canCancel =
    !terminalStatuses.has(execution.status) &&
    execution.cancellation_requested_at === null;

  return (
    <div className="run-actions">
      <Link
        className="button-secondary"
        href={`/governance?action=${encodeURIComponent(execution.governance_action_id)}`}
      >
        Inspect approval
      </Link>
      {canStart ? (
        <form action={startSandboxExecution.bind(null, execution.id)}>
          <button type="submit">Start approved execution</button>
        </form>
      ) : null}
      {canCancel ? (
        <form action={cancelSandboxExecution.bind(null, execution.id)}>
          <button className="button-secondary" type="submit">
            Request cancellation
          </button>
        </form>
      ) : null}
    </div>
  );
}

export default async function SandboxPage({
  searchParams,
}: {
  searchParams: Promise<{
    execution?: string;
    updated?: string;
    error?: string;
  }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");

  const params = await searchParams;
  const page = await getSandboxExecutions();
  const selected = params.execution
    ? await getSandboxExecution(params.execution)
    : null;

  return (
    <main className="settings-shell agents-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / SANDBOX</p>
          <h1>Isolated execution with cleanup proof</h1>
          <p className="lede">
            Execute only the exact immutable website project under the reviewed
            static profile. Every launch crosses R2 approval and a live policy
            recheck; runtime evidence remains bounded, and no terminal success
            is accepted without verified zero-resource cleanup.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/website-projects">
            Website projects
          </Link>
          <Link className="text-link" href="/governance">
            Governance
          </Link>
          <Link className="text-link" href="/workspace">
            Business workspace
          </Link>
          <form action={logout}>
            <button className="button-secondary" type="submit">
              Sign out
            </button>
          </form>
        </nav>
      </header>

      {params.updated && updates[params.updated] ? (
        <p className="notice notice--success" role="status">
          {updates[params.updated]}
        </p>
      ) : null}
      {params.error && errors[params.error] ? (
        <p className="notice notice--error" role="alert">
          {errors[params.error]}
        </p>
      ) : null}
      {!page ? (
        <p className="notice notice--error" role="alert">
          Sandbox history could not be loaded. No execution state is being
          assumed.
        </p>
      ) : null}

      {page ? (
        <>
          <section className="panel" aria-labelledby="sandbox-request-heading">
            <p className="eyebrow">PINNED REQUEST</p>
            <h2 id="sandbox-request-heading">Request execution</h2>
            <p>
              This pins the current active project, approved specification,
              source/build digests, route set, sandbox profile, and policy
              action. It does not start code before explicit owner approval.
            </p>
            <form className="run-actions" action={requestSandboxExecution}>
              <button type="submit">Request isolated execution</button>
            </form>
          </section>

          <section className="panel" aria-labelledby="sandbox-history-heading">
            <p className="eyebrow">SELECTED-BUSINESS HISTORY</p>
            <h2 id="sandbox-history-heading">
              Executions ({page.total_executions})
            </h2>
            {page.executions.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Created</th>
                      <th>Project</th>
                      <th>Status</th>
                      <th>Governance</th>
                      <th>Cleanup</th>
                      <th>Inspect</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.executions.map((execution) => (
                      <tr key={execution.id}>
                        <td>{timestamp(execution.created_at)} UTC</td>
                        <td>v{execution.website_project_version}</td>
                        <td>{execution.status}</td>
                        <td>{execution.governance_status}</td>
                        <td>
                          {execution.cleanup_status}
                          {execution.final_labeled_resource_count !== null
                            ? ` / ${execution.final_labeled_resource_count} resources`
                            : ""}
                        </td>
                        <td>
                          <Link
                            className="text-link"
                            href={`/sandbox?execution=${encodeURIComponent(execution.id)}`}
                          >
                            Evidence
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="fine-print">No sandbox request exists.</p>
            )}
          </section>

          {params.execution && !selected ? (
            <p className="notice notice--error" role="alert">
              That execution could not be loaded for the selected business.
            </p>
          ) : null}

          {selected ? (
            <section className="panel" aria-labelledby="sandbox-detail-heading">
              <div className="agent-card__heading">
                <div>
                  <p className="eyebrow">DURABLE EXECUTION</p>
                  <h2 id="sandbox-detail-heading">{selected.id}</h2>
                </div>
                <span className={`status-pill status-pill--${selected.status}`}>
                  {selected.status}
                </span>
              </div>

              <ExecutionActions execution={selected} />
              <div className="agent-contract-grid">
                <div>
                  <span>Project / specification</span>
                  <strong>
                    v{selected.website_project_version} / v
                    {selected.website_specification_version}
                  </strong>
                </div>
                <div>
                  <span>Profile</span>
                  <strong>
                    {selected.profile_id}@{selected.profile_version}
                  </strong>
                </div>
                <div>
                  <span>Governance</span>
                  <strong>
                    {selected.governance_risk_class} /{" "}
                    {selected.governance_status}
                  </strong>
                </div>
                <div>
                  <span>Cleanup</span>
                  <strong>
                    {selected.cleanup_status} / resources{" "}
                    {selected.final_labeled_resource_count ?? "pending"}
                  </strong>
                </div>
              </div>

              <p>{selected.governance_rationale}</p>
              {selected.cancellation_requested_at ? (
                <p className="notice notice--warning">
                  Cancellation requested at{" "}
                  {timestamp(selected.cancellation_requested_at)} UTC.
                </p>
              ) : null}
              {selected.termination_reason ? (
                <p className="notice notice--warning">
                  Termination: {selected.termination_reason}
                </p>
              ) : null}

              <details>
                <summary>Inspect immutable request pins</summary>
                <pre className="context-preview">
                  {JSON.stringify(
                    {
                      website_project_id: selected.website_project_id,
                      website_project_version: selected.website_project_version,
                      website_specification_id:
                        selected.website_specification_id,
                      website_specification_version:
                        selected.website_specification_version,
                      source_digest: selected.source_digest,
                      build_digest: selected.build_digest,
                      source_archive_sha256: selected.source_archive_sha256,
                      source_archive_size_bytes:
                        selected.source_archive_size_bytes,
                      routes: selected.routes,
                      request_digest: selected.request_digest,
                      policy_version_id: selected.policy_version_id,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>

              <details>
                <summary>Inspect runtime and cleanup evidence</summary>
                <Evidence
                  title="Effective limits"
                  value={selected.effective_limits}
                />
                <Evidence
                  title="Route results"
                  value={selected.route_results}
                />
                <Evidence
                  title="Process result"
                  value={selected.process_results}
                />
                <Evidence
                  title="Standard output (bounded text)"
                  value={selected.stdout_excerpt}
                />
                <Evidence
                  title="Standard error (bounded text)"
                  value={selected.stderr_excerpt}
                />
                <Evidence
                  title="Evidence digests"
                  value={{
                    runtime_image_id: selected.runtime_image_id,
                    effective_limits_digest: selected.effective_limits_digest,
                    stdout_sha256: selected.stdout_sha256,
                    stderr_sha256: selected.stderr_sha256,
                    cleanup_receipt_digest: selected.cleanup_receipt_digest,
                    cleanup_attempts: selected.cleanup_attempts,
                    worker_recovery_count: selected.worker_recovery_count,
                    heartbeat_at: selected.heartbeat_at,
                  }}
                />
              </details>
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
