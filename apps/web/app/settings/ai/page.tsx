import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../../lib/auth";
import { getBusinesses } from "../../../lib/businesses";
import { getModelGateway } from "../../../lib/model-gateway";
import {
  logout,
  runModelGatewayCheck,
  validateModelProvider,
} from "../../actions";

export const dynamic = "force-dynamic";

const errors: Record<string, string> = {
  budget:
    "The request was stopped before execution because its budget was too small.",
  disabled: "No routed provider is configured with a usable key.",
  fallback: "Sensitive requests cannot use fallback routing.",
  provider: "The provider could not complete the request.",
  unavailable: "The model gateway is temporarily unavailable.",
};

const updates: Record<string, string> = {
  generated: "The live provider request completed and its usage was persisted.",
  validated:
    "Provider validation completed. The recorded status is shown below.",
};

function usd(microusd: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 6,
  }).format(microusd / 1_000_000);
}

function timestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

export default async function AiSettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; updated?: string }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const gateway = await getModelGateway();
  const { error, updated } = await searchParams;

  return (
    <main className="settings-shell ai-settings-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / MODEL GATEWAY</p>
          <h1>Provider-independent AI routing</h1>
          <p className="lede">
            Credentials stay server-side. Calls are budgeted, routed, and
            recorded without persisting prompts or model output.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Business workspace
          </Link>
          <Link className="text-link" href="/settings/security">
            Security
          </Link>
          <form action={logout}>
            <button className="button-secondary" type="submit">
              Sign out
            </button>
          </form>
        </nav>
      </header>

      {error && errors[error] ? (
        <p className="notice notice--error" role="alert">
          {errors[error]}
        </p>
      ) : null}
      {updated && updates[updated] ? (
        <p className="notice notice--success" role="status">
          {updates[updated]}
        </p>
      ) : null}
      {!gateway ? (
        <p className="notice notice--error" role="alert">
          Gateway state could not be verified. No provider status is being
          assumed.
        </p>
      ) : null}

      {gateway ? (
        <>
          <section className="ai-summary" aria-label="Gateway usage summary">
            <article className="panel">
              <span>Successful calls</span>
              <strong>{gateway.usage.calls}</strong>
            </article>
            <article className="panel">
              <span>Persisted tokens</span>
              <strong>{gateway.usage.total_tokens}</strong>
            </article>
            <article className="panel">
              <span>Estimated provider cost</span>
              <strong>{usd(gateway.usage.estimated_cost_microusd)}</strong>
            </article>
          </section>

          <section className="panel" aria-labelledby="providers-heading">
            <p className="eyebrow">CONFIGURATION VALIDATION</p>
            <h2 id="providers-heading">Providers</h2>
            <div className="provider-grid">
              {gateway.providers.map((provider) => (
                <article className="provider-card" key={provider.name}>
                  <div>
                    <h3>{provider.name}</h3>
                    <span
                      className={`status-pill status-pill--${provider.configured ? "active" : "muted"}`}
                    >
                      {provider.configured ? "Key configured" : "Disabled"}
                    </span>
                  </div>
                  <code>{provider.model}</code>
                  <p>
                    Validation: {provider.validation_status}
                    {provider.validated_at
                      ? ` · ${timestamp(provider.validated_at)} UTC`
                      : ""}
                  </p>
                  <form action={validateModelProvider}>
                    <input
                      type="hidden"
                      name="provider"
                      value={provider.name}
                    />
                    <button
                      className="button-secondary"
                      type="submit"
                      disabled={!provider.configured}
                    >
                      Validate provider
                    </button>
                  </form>
                </article>
              ))}
            </div>
          </section>

          <section className="settings-grid">
            <article className="panel">
              <p className="eyebrow">ROUTING POLICY</p>
              <h2>Primary and fallback</h2>
              <dl className="compact-definition">
                <div>
                  <dt>Primary</dt>
                  <dd>{gateway.primary_provider}</dd>
                </div>
                <div>
                  <dt>Fallback order</dt>
                  <dd>{gateway.fallback_providers.join(" → ") || "None"}</dd>
                </div>
                <div>
                  <dt>Task routes</dt>
                  <dd>
                    {Object.keys(gateway.task_routes).length
                      ? Object.entries(gateway.task_routes)
                          .map(
                            ([task, route]) =>
                              `${task}: ${route.provider}/${route.model}`,
                          )
                          .join(", ")
                      : "Default route only"}
                  </dd>
                </div>
              </dl>
              <p className="fine-print">
                Fallback requires an explicit standard-sensitivity request.
                Sensitive content is never forwarded to another provider.
              </p>
            </article>

            <article className="panel">
              <p className="eyebrow">LIVE ACCEPTANCE CHECK</p>
              <h2>Run a budgeted provider call</h2>
              <p>
                Sends a fixed, non-sensitive health prompt through the real
                primary/fallback route with a 32-token output ceiling and a
                $0.002 maximum estimated cost.
              </p>
              <form action={runModelGatewayCheck}>
                <button type="submit">Run live gateway check</button>
              </form>
              <p className="fine-print">
                This action incurs provider usage. It never includes business
                profile data.
              </p>
            </article>
          </section>

          <section className="panel" aria-labelledby="registry-heading">
            <p className="eyebrow">GOVERNED MODEL REGISTRY</p>
            <h2 id="registry-heading">Models and budget rates</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th>Model</th>
                    <th>Input / 1M</th>
                    <th>Output / 1M</th>
                    <th>Capabilities</th>
                  </tr>
                </thead>
                <tbody>
                  {gateway.models.map((model) => (
                    <tr key={`${model.provider}/${model.model}`}>
                      <td>{model.provider}</td>
                      <td>
                        <code>{model.model}</code>
                      </td>
                      <td>${model.input_microusd_per_token}</td>
                      <td>${model.output_microusd_per_token}</td>
                      <td>streaming · structured JSON</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel" aria-labelledby="usage-heading">
            <p className="eyebrow">PERSISTED ATTEMPTS</p>
            <h2 id="usage-heading">Recent usage and failures</h2>
            {gateway.recent_calls.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Route</th>
                      <th>Status</th>
                      <th>Tokens</th>
                      <th>Cost</th>
                      <th>Latency</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gateway.recent_calls.map((call) => (
                      <tr key={`${call.operation_id}-${call.attempt_number}`}>
                        <td>{timestamp(call.created_at)} UTC</td>
                        <td>
                          {call.provider}/{call.model}
                          {call.fallback_from
                            ? ` (from ${call.fallback_from})`
                            : ""}
                        </td>
                        <td>{call.error_type ?? call.status}</td>
                        <td>{call.input_tokens + call.output_tokens}</td>
                        <td>{usd(call.estimated_cost_microusd)}</td>
                        <td>{call.latency_ms} ms</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="fine-print">No model call has been recorded.</p>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
