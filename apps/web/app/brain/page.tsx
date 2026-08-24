import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import {
  contextSourceTypes,
  type ContextSourceType,
  getBusinessContext,
} from "../../lib/business-brain";
import { getBusinesses } from "../../lib/businesses";
import { logout } from "../actions";

export const dynamic = "force-dynamic";

const sourceLabels: Record<ContextSourceType, string> = {
  business_profile: "Business profile",
  approved_profile: "Approved profile",
  approved_goals: "Approved strategic goals",
  products_services: "Products / services",
  brand: "Brand",
  operating_context: "Assets / constraints",
  operational_goals: "Operational goals",
  current_tasks: "Current tasks",
  knowledge: "Retrieved knowledge",
  relevant_memories: "Relevant curated memories",
};

function selectedSources(value: string | string[] | undefined) {
  if (value === undefined) return [...contextSourceTypes];
  const values = Array.isArray(value) ? value : [value];
  return values.filter((item): item is ContextSourceType =>
    contextSourceTypes.includes(item as ContextSourceType),
  );
}

function tokenBudget(value: string | undefined): number {
  const parsed = Number(value ?? 4096);
  return Number.isInteger(parsed) && parsed >= 256 && parsed <= 32768
    ? parsed
    : 4096;
}

function purpose(value: string | undefined): string {
  return /^[a-z][a-z0-9_.-]{0,79}$/.test(value ?? "")
    ? (value as string)
    : "general";
}

function timestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

export default async function BusinessBrainPage({
  searchParams,
}: {
  searchParams: Promise<{
    purpose?: string;
    token_budget?: string;
    sources?: string | string[];
    knowledge_query?: string;
    memory_query?: string;
  }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const params = await searchParams;
  const sources = selectedSources(params.sources);
  const budget = tokenBudget(params.token_budget);
  const selectedPurpose = purpose(params.purpose);
  const knowledgeQuery = params.knowledge_query?.trim().slice(0, 500) ?? "";
  const memoryQuery = params.memory_query?.trim().slice(0, 500) ?? "";
  const brain = await getBusinessContext({
    purpose: selectedPurpose,
    tokenBudget: budget,
    sourceTypes: sources,
    knowledgeQuery,
    memoryQuery,
  });
  const included =
    brain?.sources.filter((source) => source.selection_status === "included") ??
    [];
  const excluded =
    brain?.sources.filter((source) => source.selection_status === "excluded") ??
    [];

  return (
    <main className="settings-shell brain-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / BUSINESS BRAIN</p>
          <h1>Unified, provenance-first context</h1>
          <p className="lede">
            Context is assembled only from the selected business and approved or
            live owner-controlled sources. Drafts and unavailable future domains
            are never inferred.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Business workspace
          </Link>
          <Link className="text-link" href="/settings/ai">
            AI gateway
          </Link>
          <Link className="text-link" href="/agents">
            Agents
          </Link>
          <Link className="text-link" href="/tasks">
            Tasks
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
          <Link className="text-link" href="/knowledge">
            Knowledge
          </Link>
          <Link className="text-link" href="/memory">
            Memory
          </Link>
          <form action={logout}>
            <button className="button-secondary" type="submit">
              Sign out
            </button>
          </form>
        </nav>
      </header>

      {!brain ? (
        <p className="notice notice--error" role="alert">
          Business context could not be assembled. No source state is being
          assumed.
        </p>
      ) : null}

      <section className="panel" aria-labelledby="builder-heading">
        <p className="eyebrow">SOURCE SELECTION</p>
        <h2 id="builder-heading">Build controls</h2>
        <form className="brain-controls" action="/brain" method="get">
          <div>
            <label htmlFor="context-purpose">Purpose</label>
            <input
              id="context-purpose"
              name="purpose"
              defaultValue={selectedPurpose}
              pattern="[a-z][a-z0-9_.-]{0,79}"
              maxLength={80}
              required
            />
          </div>
          <div>
            <label htmlFor="context-budget">Token budget</label>
            <input
              id="context-budget"
              name="token_budget"
              type="number"
              min={256}
              max={32768}
              defaultValue={budget}
              required
            />
          </div>
          <fieldset>
            <legend>Eligible source types</legend>
            <input type="hidden" name="sources" value="" />
            <div className="source-checkboxes">
              {contextSourceTypes.map((source) => (
                <label key={source}>
                  <input
                    type="checkbox"
                    name="sources"
                    value={source}
                    defaultChecked={sources.includes(source)}
                  />
                  {sourceLabels[source]}
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <label htmlFor="knowledge-query">Knowledge retrieval query</label>
            <input
              id="knowledge-query"
              name="knowledge_query"
              defaultValue={knowledgeQuery}
              maxLength={500}
              placeholder="Required only when retrieved knowledge is selected"
            />
          </div>
          <div>
            <label htmlFor="memory-query">Memory text filter (optional)</label>
            <input
              id="memory-query"
              name="memory_query"
              defaultValue={memoryQuery}
              maxLength={500}
              placeholder="Filter active, unexpired curated memory"
            />
          </div>
          <button type="submit">Rebuild context</button>
        </form>
        <p className="fine-print">
          Budgeting uses a conservative upper bound of one token per UTF-8 byte.
          This may select less context than a provider tokenizer, but never more
          than the declared ceiling.
        </p>
      </section>

      {brain ? (
        <>
          <section className="ai-summary" aria-label="Context summary">
            <article className="panel">
              <span>Included sources</span>
              <strong>{included.length}</strong>
            </article>
            <article className="panel">
              <span>Conservative tokens</span>
              <strong>
                {brain.estimated_tokens} / {brain.token_budget}
              </strong>
            </article>
            <article className="panel">
              <span>Excluded sources</span>
              <strong>{excluded.length}</strong>
            </article>
          </section>

          <section className="panel" aria-labelledby="provenance-heading">
            <p className="eyebrow">PROVENANCE</p>
            <h2 id="provenance-heading">Source decisions</h2>
            <p className="fine-print">
              Context ID <code>{brain.context_id}</code> · generated{" "}
              {timestamp(brain.generated_at)} UTC
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Authority</th>
                    <th>Version</th>
                    <th>Validity</th>
                    <th>Selection</th>
                  </tr>
                </thead>
                <tbody>
                  {brain.sources.map((source) => (
                    <tr
                      key={`${source.source_type}-${source.source_reference}-${source.source_version}`}
                    >
                      <td>
                        <strong>{source.label}</strong>
                        <br />
                        <code>{source.source_reference}</code>
                      </td>
                      <td>{source.authority}</td>
                      <td>{source.source_version}</td>
                      <td>{source.validity}</td>
                      <td>
                        {source.selection_status}
                        {source.exclusion_reason
                          ? ` (${source.exclusion_reason})`
                          : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="settings-grid">
            <article className="panel">
              <p className="eyebrow">UNAVAILABLE BY DESIGN</p>
              <h2>Future sources</h2>
              <dl className="unavailable-sources">
                {Object.entries(brain.unavailable_sources).map(
                  ([source, reason]) => (
                    <div key={source}>
                      <dt>{source}</dt>
                      <dd>{reason}</dd>
                    </div>
                  ),
                )}
              </dl>
            </article>
            <article className="panel">
              <p className="eyebrow">INTEGRITY</p>
              <h2>Context fingerprint</h2>
              <p className="fine-print">
                The compiled context is deterministic for the same source
                versions, selection, purpose, and budget.
              </p>
              <code className="hash-value">{brain.context_sha256}</code>
            </article>
          </section>

          <section className="panel" aria-labelledby="payload-heading">
            <p className="eyebrow">COMPILED PAYLOAD</p>
            <h2 id="payload-heading">Model-ready context</h2>
            <pre className="context-preview">{brain.context}</pre>
          </section>
        </>
      ) : null}
    </main>
  );
}
