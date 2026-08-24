import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { getKnowledgeDashboard, searchKnowledge } from "../../lib/knowledge";
import {
  invalidateKnowledgeDocument,
  invalidateKnowledgeSource,
  logout,
  registerKnowledgeSource,
  uploadKnowledgeDocument,
} from "../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  conflict:
    "The source changed or the same content is already registered. Refresh and try again.",
  invalid:
    "The source or file is invalid. Upload bounded UTF-8 .txt, .md, .json, or .csv content.",
  "not-found": "The selected-business source or document was not found.",
  unavailable:
    "Knowledge ingestion is temporarily unavailable; no success state was assumed.",
};

const updates: Record<string, string> = {
  source: "The knowledge source and its provenance were registered.",
  indexed:
    "The document was stored, extracted, chunked, embedded, and indexed.",
  invalidated:
    "The knowledge record was invalidated and is excluded from retrieval.",
};

function timestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

export default async function KnowledgePage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; updated?: string; q?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const params = await searchParams;
  const dashboard = await getKnowledgeDashboard();
  const query = params.q?.trim() ?? "";
  const hits = query ? await searchKnowledge(query) : [];

  return (
    <main className="settings-shell tasks-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / KNOWLEDGE</p>
          <h1>Retrievable evidence with durable citations</h1>
          <p className="lede">
            Register provenance before upload. Foundora stores the original
            file, extracts bounded text, creates versioned local embeddings, and
            returns source-preserving chunk citations. Registered knowledge is
            evidence, not automatically an approved business fact.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Business workspace
          </Link>
          <Link className="text-link" href="/brain">
            Business brain
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
          Knowledge state could not be loaded.
        </p>
      ) : null}

      {dashboard ? (
        <>
          <section className="panel" aria-labelledby="register-source-heading">
            <p className="eyebrow">SOURCE REGISTRATION</p>
            <h2 id="register-source-heading">Record provenance first</h2>
            <form
              className="workspace-form task-form"
              action={registerKnowledgeSource}
            >
              <label>
                Title
                <input name="title" minLength={1} maxLength={200} required />
              </label>
              <div className="settings-grid">
                <label>
                  Source type
                  <select name="source_type" defaultValue="upload">
                    <option value="upload">Uploaded document</option>
                    <option value="reference">External reference</option>
                  </select>
                </label>
                <label>
                  Source URL (required for reference)
                  <input name="source_uri" type="url" maxLength={2048} />
                </label>
              </div>
              <label>
                Metadata (JSON object)
                <textarea name="metadata" rows={3} defaultValue="{}" />
              </label>
              <button type="submit">Register source</button>
            </form>
          </section>

          <section className="panel" aria-labelledby="knowledge-search-heading">
            <p className="eyebrow">VECTOR RETRIEVAL</p>
            <h2 id="knowledge-search-heading">Search active knowledge</h2>
            <p className="fine-print">
              Embedding contract: <code>{dashboard.embedding_model}</code>.
              Search never includes invalidated sources or documents.
            </p>
            <form className="workspace-form" method="get">
              <label>
                Query
                <input
                  name="q"
                  defaultValue={query}
                  minLength={1}
                  maxLength={500}
                  required
                />
              </label>
              <button type="submit">Retrieve cited chunks</button>
            </form>
            {query && hits === null ? (
              <p className="notice notice--error">
                Retrieval failed; no results were assumed.
              </p>
            ) : null}
            {query && hits?.length === 0 ? (
              <p className="fine-print">No active chunk matched this query.</p>
            ) : null}
            {hits?.map((hit) => (
              <article className="agent-card" key={hit.citation.chunk_id}>
                <div className="agent-card__heading">
                  <div>
                    <h3>{hit.citation.source_title}</h3>
                    <code>
                      {hit.citation.filename}#chunk-{hit.citation.chunk_ordinal}
                    </code>
                  </div>
                  <span className="status-pill status-pill--completed">
                    {hit.score.toFixed(4)}
                  </span>
                </div>
                <p>{hit.text}</p>
                <p className="fine-print">
                  Characters {hit.citation.start_character}–
                  {hit.citation.end_character} · SHA-256{" "}
                  <code>{hit.citation.content_sha256}</code>
                </p>
                {hit.citation.source_uri ? (
                  <a
                    className="text-link"
                    href={hit.citation.source_uri}
                    rel="noreferrer"
                    target="_blank"
                  >
                    Open registered source
                  </a>
                ) : null}
              </article>
            ))}
          </section>

          <section className="panel" aria-labelledby="knowledge-ledger-heading">
            <p className="eyebrow">SELECTED-BUSINESS LEDGER</p>
            <h2 id="knowledge-ledger-heading">Sources and indexed documents</h2>
            {dashboard.sources.length === 0 ? (
              <p className="fine-print">
                No knowledge source has been registered for this business.
              </p>
            ) : null}
            {dashboard.sources.map((source) => (
              <article className="agent-card" key={source.id}>
                <div className="agent-card__heading">
                  <div>
                    <h3>{source.title}</h3>
                    <code>{source.id}</code>
                  </div>
                  <span
                    className={`status-pill status-pill--${source.status === "active" ? "completed" : "cancelled"}`}
                  >
                    {source.status}
                  </span>
                </div>
                <p className="fine-print">
                  {source.source_type} · revision {source.revision} · registered{" "}
                  {timestamp(source.created_at)} UTC
                </p>
                {source.source_uri ? (
                  <a
                    className="text-link"
                    href={source.source_uri}
                    rel="noreferrer"
                    target="_blank"
                  >
                    {source.source_uri}
                  </a>
                ) : null}
                {source.status === "active" ? (
                  <form
                    className="workspace-form"
                    action={uploadKnowledgeDocument.bind(null, source.id)}
                  >
                    <label>
                      UTF-8 document
                      <input
                        name="file"
                        type="file"
                        accept={dashboard.supported_file_types.join(",")}
                        required
                      />
                    </label>
                    <button type="submit">Upload and index</button>
                  </form>
                ) : null}
                {source.documents.map((document) => (
                  <div className="agent-contract-grid" key={document.id}>
                    <div>
                      <span>Document</span>
                      <strong>{document.filename}</strong>
                      <small>
                        {document.status} · {document.chunk_count} chunks ·{" "}
                        {document.byte_size} bytes
                      </small>
                    </div>
                    <div>
                      <span>Integrity</span>
                      <strong>{document.content_sha256}</strong>
                      <small>
                        {document.embedding_model} /{" "}
                        {document.embedding_dimensions} dimensions
                      </small>
                    </div>
                    {document.status === "indexed" ? (
                      <form
                        className="workspace-form"
                        action={invalidateKnowledgeDocument.bind(
                          null,
                          document.id,
                          document.revision,
                        )}
                      >
                        <label>
                          Reason
                          <input
                            name="reason"
                            minLength={1}
                            maxLength={500}
                            required
                          />
                        </label>
                        <button className="button-danger" type="submit">
                          Invalidate document
                        </button>
                      </form>
                    ) : null}
                  </div>
                ))}
                {source.status === "active" ? (
                  <form
                    className="workspace-form"
                    action={invalidateKnowledgeSource.bind(
                      null,
                      source.id,
                      source.revision,
                    )}
                  >
                    <label>
                      Source invalidation reason
                      <input
                        name="reason"
                        minLength={1}
                        maxLength={500}
                        required
                      />
                    </label>
                    <button className="button-danger" type="submit">
                      Invalidate source and active documents
                    </button>
                  </form>
                ) : null}
              </article>
            ))}
          </section>
        </>
      ) : null}
    </main>
  );
}
