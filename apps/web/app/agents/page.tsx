import Link from "next/link";
import { redirect } from "next/navigation";

import { getAgentDashboard, getAgentRun } from "../../lib/agents";
import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { cancelAgentRun, logout, runAgent } from "../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  agent: "The selected agent definition is disabled or unavailable.",
  invalid: "The objective or skill input does not match its required schema.",
  skill: "That skill version is not assigned to the selected agent version.",
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
const researchAgents = new Set([
  "market-research",
  "competitor-intelligence",
  "customer-research",
]);

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
          <p className="eyebrow">FOUNDORA / SKILL REGISTRY</p>
          <h1>Assigned capability, inspectable execution</h1>
          <p className="lede">
            Agent and skill contracts are immutable and version-pinned. The
            Founder/CEO and Chief-of-Staff produce grounded, proposed plans with
            source traceability. Research specialists analyze only explicitly
            retrieved, founder-registered evidence and flag unsupported claims.
            The Business Strategist consumes one completed supported run from
            each research role and ties every proposed artifact to approved
            facts. None can execute tools, create tasks, grant approvals, spend,
            or claim a delegation occurred. The Product &amp; Offer Agent turns
            the current approved strategy into traceable proposals that still
            require separate founder approval. The Brand Strategist converts the
            aligned approved strategy and offer into reusable proposed brand
            rules with no publishing authority.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Business workspace
          </Link>
          <Link className="text-link" href="/brain">
            Business brain
          </Link>
          <Link className="text-link" href="/strategy">
            Strategy
          </Link>
          <Link className="text-link" href="/products-offers">
            Products &amp; offers
          </Link>
          <Link className="text-link" href="/brand">
            Brand
          </Link>
          <Link className="text-link" href="/tasks">
            Task engine
          </Link>
          <Link className="text-link" href="/workflows">
            Workflow engine
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
          <Link className="text-link" href="/memory">
            Memory
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
                    <span>Assigned skills</span>
                    <strong>
                      {definition.assigned_skills.length
                        ? definition.assigned_skills
                            .map(
                              (skill) => `${skill.skill_id}@${skill.version}`,
                            )
                            .join(", ")
                        : "None"}
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
                    {definition.agent_id === "founder-ceo" ||
                    definition.agent_id === "chief-of-staff-planning"
                      ? "Founder objective for advisory planning"
                      : "Read-only objective"}
                  </label>
                  <textarea
                    id={`objective-${definition.agent_id}`}
                    name="objective"
                    defaultValue={
                      definition.agent_id === "founder-ceo"
                        ? "Review the current business state and propose the most important grounded priorities and specialist work."
                        : definition.agent_id === "chief-of-staff-planning"
                          ? "Turn the current objective and business state into a proposed, dependency-aware plan."
                          : "Inspect the selected business context and identify its most important grounded observation."
                    }
                    minLength={1}
                    maxLength={500}
                    rows={3}
                    required
                  />
                  {researchAgents.has(definition.agent_id) ? (
                    <>
                      <label htmlFor={`research-${definition.agent_id}`}>
                        Evidence search query
                      </label>
                      <textarea
                        id={`research-${definition.agent_id}`}
                        name="research_query"
                        defaultValue={
                          definition.agent_id === "market-research"
                            ? "What cited market trends and demand signals are present for this business?"
                            : definition.agent_id === "competitor-intelligence"
                              ? "Which competitors are explicitly named, and what cited positioning, pricing, features, or whitespace are documented?"
                              : "What cited ICP, jobs-to-be-done, pain points, buying triggers, and objections are documented?"
                        }
                        minLength={1}
                        maxLength={500}
                        rows={3}
                        required
                      />
                      <p className="form-help">
                        Searches active evidence already registered under
                        Knowledge. No public-web provider is configured or
                        implied.
                      </p>
                    </>
                  ) : null}
                  {definition.agent_id === "business-strategist" ? (
                    <fieldset>
                      <legend>Required completed research evidence</legend>
                      {[...researchAgents].map((researchAgentId) => {
                        const candidates = dashboard.runs.filter(
                          (run) =>
                            run.agent_id === researchAgentId &&
                            run.status === "completed",
                        );
                        return (
                          <div key={researchAgentId}>
                            <label
                              htmlFor={`strategy-evidence-${researchAgentId}`}
                            >
                              {researchAgentId}
                            </label>
                            {candidates.length ? (
                              <select
                                id={`strategy-evidence-${researchAgentId}`}
                                name="research_run_ids"
                                required
                                defaultValue={candidates[0].id}
                              >
                                {candidates.map((run) => (
                                  <option key={run.id} value={run.id}>
                                    {timestamp(run.completed_at)} UTC — {run.id}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <p className="notice notice--warning">
                                Complete a supported {researchAgentId} run
                                first.
                              </p>
                            )}
                          </div>
                        );
                      })}
                      <p className="form-help">
                        The newest completed run for each specialist is pinned.
                        Strategy remains proposed until separately approved.
                      </p>
                    </fieldset>
                  ) : null}
                  <label htmlFor={`skill-${definition.agent_id}`}>
                    Assigned skill
                  </label>
                  <select
                    id={`skill-${definition.agent_id}`}
                    name="skill_id"
                    defaultValue={definition.assigned_skills[0]?.skill_id ?? ""}
                  >
                    <option value="">No skill</option>
                    {definition.assigned_skills.map((skill) => (
                      <option key={skill.version_id} value={skill.skill_id}>
                        {skill.skill_id}@{skill.version}
                      </option>
                    ))}
                  </select>
                  <label htmlFor={`skill-input-${definition.agent_id}`}>
                    Skill input (JSON)
                  </label>
                  <textarea
                    id={`skill-input-${definition.agent_id}`}
                    name="skill_input"
                    defaultValue={'{"focus":"most important business context"}'}
                    rows={3}
                  />
                  <button type="submit" disabled={!definition.enabled}>
                    Queue manual R0 advisory run
                  </button>
                </form>
              </article>
            ))}
          </section>

          <section className="agent-registry" aria-labelledby="skills-heading">
            <div className="section-heading">
              <p className="eyebrow">SKILL REGISTRY</p>
              <h2 id="skills-heading">Immutable capability contracts</h2>
            </div>
            {dashboard.skills.map((skill) => (
              <article className="panel agent-card" key={skill.version_id}>
                <div className="agent-card__heading">
                  <div>
                    <h3>{skill.display_name}</h3>
                    <code>
                      {skill.skill_id}@{skill.version}
                    </code>
                  </div>
                  <span className="status-pill status-pill--active">
                    {skill.risk_class}
                  </span>
                </div>
                <p>{skill.description}</p>
                <div className="agent-contract-grid">
                  <div>
                    <span>Compatible agents</span>
                    <strong>{skill.compatible_agents.join(", ")}</strong>
                  </div>
                  <div>
                    <span>Tools required</span>
                    <strong>
                      {skill.tool_requirements.length
                        ? skill.tool_requirements.join(", ")
                        : "None"}
                    </strong>
                  </div>
                  <div>
                    <span>Permissions</span>
                    <strong>{skill.permissions.join(", ")}</strong>
                  </div>
                </div>
                <details>
                  <summary>Inspect workflow, schemas, and evaluation</summary>
                  <div className="agent-boundaries">
                    <div>
                      <h4>Declarative workflow</h4>
                      <ol>
                        {skill.workflow.map((step) => (
                          <li key={step}>{step}</li>
                        ))}
                      </ol>
                      <h4>Evaluation rubric</h4>
                      <ul>
                        {skill.evaluation_rubric.map((criterion) => (
                          <li key={criterion}>{criterion}</li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <h4>Input schema</h4>
                      <pre className="context-preview">
                        {JSON.stringify(skill.input_schema, null, 2)}
                      </pre>
                      <h4>Output schema</h4>
                      <pre className="context-preview">
                        {JSON.stringify(skill.output_schema, null, 2)}
                      </pre>
                    </div>
                  </div>
                </details>
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
                  <span>Skill version</span>
                  <strong>
                    {selectedRun.skill_id
                      ? `${selectedRun.skill_id}@${selectedRun.skill_version}`
                      : "No skill"}
                  </strong>
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
              {selectedRun.executive_plan_trace ? (
                <article className="panel">
                  <p className="eyebrow">EXECUTIVE PLAN TRACE</p>
                  <h3>Pinned advisory evidence</h3>
                  <div className="agent-contract-grid">
                    <div>
                      <span>Context ID</span>
                      <code>{selectedRun.executive_plan_trace.context_id}</code>
                    </div>
                    <div>
                      <span>Context integrity</span>
                      <strong>
                        {selectedRun.executive_plan_trace.output_context_matches
                          ? "Output matches pinned context"
                          : "No validated output match yet"}
                      </strong>
                    </div>
                    <div>
                      <span>Authority</span>
                      <strong>Advisory only; nothing executed</strong>
                    </div>
                  </div>
                  <details>
                    <summary>Inspect exact included source references</summary>
                    <ul>
                      {selectedRun.executive_plan_trace.source_references.map(
                        (reference) => (
                          <li key={reference}>
                            <code>{reference}</code>
                          </li>
                        ),
                      )}
                    </ul>
                  </details>
                </article>
              ) : null}
              {selectedRun.research_trace ? (
                <article className="panel">
                  <p className="eyebrow">RESEARCH EVIDENCE TRACE</p>
                  <h3>Exact sources supplied to the specialist</h3>
                  <div className="agent-contract-grid">
                    <div>
                      <span>Search boundary</span>
                      <strong>{selectedRun.research_trace.provider}</strong>
                    </div>
                    <div>
                      <span>Validated output</span>
                      <strong>
                        {selectedRun.research_trace.output_validated
                          ? "Runtime validation passed"
                          : "No validated output yet"}
                      </strong>
                    </div>
                    <div>
                      <span>Authority</span>
                      <strong>Advisory only; nothing executed</strong>
                    </div>
                  </div>
                  <p>{selectedRun.research_trace.query}</p>
                  {selectedRun.research_trace.evidence.length ? (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Source</th>
                            <th>Retrieved</th>
                            <th>Evidence ID / integrity</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedRun.research_trace.evidence.map((item) => (
                            <tr key={item.evidence_id}>
                              <td>
                                <strong>{item.source_title}</strong>
                                <br />
                                <code>{item.source}</code>
                              </td>
                              <td>{item.retrieval_date}</td>
                              <td>
                                <code>{item.evidence_id}</code>
                                <br />
                                <code>{item.content_sha256}</code>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="notice notice--warning">
                      No matching registered evidence was retrieved. Any
                      resulting claim must remain explicitly unsupported.
                    </p>
                  )}
                </article>
              ) : null}
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
                      <th>Skill</th>
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
                        <td>
                          {run.skill_id
                            ? `${run.skill_id}@${run.skill_version}`
                            : "-"}
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
