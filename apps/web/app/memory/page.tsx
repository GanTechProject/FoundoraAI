import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { getMemoryDashboard, memoryTypes } from "../../lib/memory";
import {
  decideMemoryProposal,
  invalidateMemory,
  logout,
  proposeMemory,
  updateMemoryPolicy,
} from "../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  conflict: "The policy or memory changed. Reload before deciding again.",
  invalid:
    "The curator rejected this proposal. Check its type, evidence, expiry, and secret-free content.",
  "not-found": "The selected-business memory record was not found.",
  unavailable:
    "Memory state is temporarily unavailable; no success was assumed.",
};
const updates: Record<string, string> = {
  policy: "The selected-business acceptance policy was updated.",
  proposed: "The curator recorded a proposal for founder review.",
  accepted: "The founder accepted the proposal into durable memory.",
  merged: "The exact duplicate was merged into the existing memory provenance.",
  rejected: "The founder rejected the proposal.",
  invalidated: "The stale memory was invalidated and removed from retrieval.",
};

function timestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

export default async function MemoryPage({
  searchParams,
}: {
  searchParams: Promise<{
    error?: string;
    updated?: string;
    q?: string;
    memory_type?: string;
  }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const params = await searchParams;
  const selectedType = memoryTypes.includes(params.memory_type as never)
    ? params.memory_type
    : "";
  const dashboard = await getMemoryDashboard({
    query: params.q?.trim(),
    memoryType: selectedType,
  });

  return (
    <main className="settings-shell tasks-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / MEMORY</p>
          <h1>Curated memory with visible provenance</h1>
          <p className="lede">
            The curator proposes; policy or the founder decides. Facts require
            explicit founder approval, assumptions stay labeled as assumptions,
            exact duplicates merge, and stale memory is invalidatable.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Business workspace
          </Link>
          <Link className="text-link" href="/brain">
            Business brain
          </Link>
          <Link className="text-link" href="/knowledge">
            Knowledge
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
        <p className="notice notice--error">
          Memory state could not be loaded.
        </p>
      ) : null}

      {dashboard ? (
        <>
          <section className="panel" aria-labelledby="policy-heading">
            <p className="eyebrow">ACCEPTANCE POLICY</p>
            <h2 id="policy-heading">Founder review is the safe default</h2>
            <p className="fine-print">
              Semantic facts, decisions, and preferences always require founder
              acceptance. Automatic acceptance also requires verified system
              provenance and the confidence threshold.
            </p>
            <form className="workspace-form" action={updateMemoryPolicy}>
              <input
                type="hidden"
                name="expected_revision"
                value={dashboard.policy.revision}
              />
              <div className="settings-grid">
                {(
                  ["working", "episodic", "workflow", "evaluation"] as const
                ).map((type) => (
                  <label key={type} className="checkbox-row">
                    <input
                      type="checkbox"
                      name="automatic_accept_types"
                      value={type}
                      defaultChecked={dashboard.policy.automatic_accept_types.includes(
                        type,
                      )}
                    />
                    Auto-accept {type}
                  </label>
                ))}
              </div>
              <label>
                Minimum automatic confidence
                <input
                  name="minimum_confidence"
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  defaultValue={dashboard.policy.minimum_confidence}
                  required
                />
              </label>
              <button type="submit">Save memory policy</button>
            </form>
          </section>

          <section className="panel" aria-labelledby="curator-heading">
            <p className="eyebrow">MEMORY CURATOR</p>
            <h2 id="curator-heading">Propose durable memory</h2>
            <p className="fine-print">
              Never enter passwords, tokens, API keys, private keys, or other
              secrets. Working memory requires a task, agent run, or workflow
              run UUID and an expiry within seven days.
            </p>
            <form className="workspace-form task-form" action={proposeMemory}>
              <div className="settings-grid">
                <label>
                  Memory type
                  <select name="memory_type" defaultValue="semantic">
                    {memoryTypes.map((type) => (
                      <option value={type} key={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Epistemic status
                  <select name="epistemic_status" defaultValue="assumption">
                    <option value="observation">observation</option>
                    <option value="assumption">assumption</option>
                    <option value="fact">fact</option>
                    <option value="decision">decision</option>
                    <option value="preference">preference</option>
                    <option value="procedure">procedure</option>
                    <option value="evaluation">evaluation</option>
                  </select>
                </label>
              </div>
              <label>
                Title
                <input name="title" minLength={1} maxLength={200} required />
              </label>
              <label>
                Content
                <textarea
                  name="content"
                  rows={5}
                  minLength={1}
                  maxLength={8000}
                  required
                />
              </label>
              <label>
                Confidence
                <input
                  name="confidence"
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  defaultValue="0.8"
                  required
                />
              </label>
              <div className="settings-grid">
                <label>
                  Execution type (working only)
                  <select name="execution_type" defaultValue="">
                    <option value="">Not execution-scoped</option>
                    <option value="task">task</option>
                    <option value="agent_run">agent run</option>
                    <option value="workflow_run">workflow run</option>
                  </select>
                </label>
                <label>
                  Execution UUID
                  <input name="execution_id" />
                </label>
                <label>
                  Expiry (working required)
                  <input name="expires_at" type="datetime-local" />
                </label>
              </div>
              <div className="settings-grid">
                <label>
                  Provenance type
                  <select name="source_kind" defaultValue="founder_input">
                    <option value="founder_input">founder input</option>
                    <option value="knowledge_chunk">knowledge chunk</option>
                    <option value="task">task</option>
                    <option value="agent_run">agent run</option>
                    <option value="workflow_run">workflow run</option>
                  </select>
                </label>
                <label>
                  Source UUID (system sources)
                  <input name="source_id" />
                </label>
                <label>
                  External source URL
                  <input name="source_uri" type="url" maxLength={2048} />
                </label>
              </div>
              <label>
                Source label
                <input
                  name="source_label"
                  minLength={1}
                  maxLength={200}
                  required
                />
              </label>
              <label>
                Evidence excerpt
                <textarea name="source_excerpt" rows={3} maxLength={1000} />
              </label>
              <label>
                Source metadata (JSON)
                <textarea name="source_metadata" rows={3} defaultValue="{}" />
              </label>
              <button type="submit">Submit curator proposal</button>
            </form>
          </section>

          <section className="panel" aria-labelledby="proposals-heading">
            <p className="eyebrow">FOUNDER REVIEW</p>
            <h2 id="proposals-heading">Pending proposals</h2>
            {dashboard.proposals.filter((item) => item.status === "pending")
              .length ? (
              <div className="task-list">
                {dashboard.proposals
                  .filter((item) => item.status === "pending")
                  .map((proposal) => (
                    <article className="task-card" key={proposal.id}>
                      <p className="eyebrow">
                        {proposal.memory_type} / {proposal.epistemic_status} /{" "}
                        {proposal.acceptance_route}
                      </p>
                      <h3>{proposal.title}</h3>
                      <p>{proposal.content}</p>
                      <p className="fine-print">
                        Confidence {proposal.confidence.toFixed(2)} · Source:{" "}
                        {proposal.source_label} ({proposal.source_kind}) ·
                        proposed {timestamp(proposal.created_at)}
                      </p>
                      {proposal.source_excerpt ? (
                        <blockquote>{proposal.source_excerpt}</blockquote>
                      ) : null}
                      <div className="settings-grid">
                        {([true, false] as const).map((accept) => (
                          <form
                            action={decideMemoryProposal.bind(
                              null,
                              proposal.id,
                              accept,
                            )}
                            key={String(accept)}
                          >
                            <input
                              type="hidden"
                              name="expected_revision"
                              value={proposal.revision}
                            />
                            <label>
                              {accept ? "Acceptance" : "Rejection"} reason
                              <input
                                name="reason"
                                minLength={1}
                                maxLength={500}
                                required
                              />
                            </label>
                            <button
                              className={
                                accept ? undefined : "button-secondary"
                              }
                              type="submit"
                            >
                              {accept
                                ? "Accept durable memory"
                                : "Reject proposal"}
                            </button>
                          </form>
                        ))}
                      </div>
                    </article>
                  ))}
              </div>
            ) : (
              <p>No proposals await founder review.</p>
            )}
          </section>

          <section className="panel" aria-labelledby="ledger-heading">
            <p className="eyebrow">RETRIEVAL FILTERS</p>
            <h2 id="ledger-heading">Durable memory ledger</h2>
            <form className="workspace-form" method="get">
              <div className="settings-grid">
                <label>
                  Text filter
                  <input name="q" defaultValue={params.q ?? ""} />
                </label>
                <label>
                  Memory type
                  <select name="memory_type" defaultValue={selectedType}>
                    <option value="">All types</option>
                    {memoryTypes.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <button type="submit">Filter memory</button>
            </form>
            {dashboard.memories.length ? (
              <div className="task-list">
                {dashboard.memories.map((memory) => (
                  <article className="task-card" key={memory.id}>
                    <p className="eyebrow">
                      {memory.memory_type} / {memory.epistemic_status} /{" "}
                      {memory.status}
                    </p>
                    <h3>{memory.title}</h3>
                    <p>{memory.content}</p>
                    <p className="fine-print">
                      Confidence {memory.confidence.toFixed(2)} · accepted via{" "}
                      {memory.accepted_via} · revision {memory.current_revision}
                    </p>
                    <h4>Visible provenance</h4>
                    <ul>
                      {memory.provenance.map((source, index) => (
                        <li key={`${source.revision}-${index}`}>
                          Revision {source.revision}: {source.source_label} (
                          {source.source_kind})
                          {source.source_uri ? (
                            <>
                              {" "}
                              ·{" "}
                              <a href={source.source_uri}>
                                {source.source_uri}
                              </a>
                            </>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                    {memory.status === "active" ? (
                      <form action={invalidateMemory.bind(null, memory.id)}>
                        <input
                          type="hidden"
                          name="expected_revision"
                          value={memory.current_revision}
                        />
                        <label>
                          Invalidation reason
                          <input
                            name="reason"
                            minLength={1}
                            maxLength={500}
                            required
                          />
                        </label>
                        <button className="button-secondary" type="submit">
                          Invalidate stale memory
                        </button>
                      </form>
                    ) : (
                      <p className="fine-print">
                        {memory.invalidation_reason ??
                          (memory.status === "expired"
                            ? "Expired and excluded from retrieval."
                            : "Inactive")}
                      </p>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <p>No memory matches these filters.</p>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
