import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuthSession } from "../../lib/auth";
import { getBusinesses } from "../../lib/businesses";
import { DeliveryStatus, getEventDashboard } from "../../lib/events";
import { logout, redriveEventDelivery } from "../actions";

export const dynamic = "force-dynamic";

const statuses = new Set<DeliveryStatus>([
  "pending",
  "retry_wait",
  "processing",
  "completed",
  "dead_letter",
]);

function timestamp(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value));
}

export default async function EventsPage({
  searchParams,
}: {
  searchParams: Promise<{
    status?: string;
    error?: string;
    updated?: string;
  }>;
}) {
  const auth = await getAuthSession();
  if (!auth) redirect("/login");
  const businesses = await getBusinesses();
  if (!businesses?.selected_business_id) redirect("/workspace");
  const params = await searchParams;
  const deliveryStatus = statuses.has(params.status as DeliveryStatus)
    ? (params.status as DeliveryStatus)
    : undefined;
  const dashboard = await getEventDashboard(deliveryStatus);

  return (
    <main className="settings-shell tasks-shell">
      <header className="settings-header">
        <div>
          <p className="eyebrow">FOUNDORA / INTERNAL EVENT BUS</p>
          <h1>Durable domain events and handler deliveries</h1>
          <p className="lede">
            Events are written with their domain transaction. PostgreSQL keeps
            the immutable envelope and every consumer outcome; Redis is never
            the durable event authority.
          </p>
        </div>
        <nav className="header-actions" aria-label="Owner navigation">
          <Link className="text-link" href="/workspace">
            Business workspace
          </Link>
          <Link className="text-link" href="/governance">
            Governance
          </Link>
          <Link className="text-link" href="/workflows">
            Workflows
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

      {params.error ? (
        <p className="notice notice--error" role="alert">
          The delivery could not be redriven. Reload its latest durable state.
        </p>
      ) : null}
      {params.updated === "redriven" ? (
        <p className="notice notice--success" role="status">
          The dead-letter delivery was returned to the pending queue.
        </p>
      ) : null}
      {!dashboard ? (
        <p className="notice notice--error" role="alert">
          Event state is unavailable. No delivery state is being assumed.
        </p>
      ) : null}

      {dashboard ? (
        <>
          <section className="panel" aria-labelledby="contracts-heading">
            <p className="eyebrow">VERSIONED CONTRACTS</p>
            <h2 id="contracts-heading">Registered event routes</h2>
            <div className="agent-grid">
              {dashboard.contracts.map((contract) => (
                <article className="agent-card" key={contract.event_type}>
                  <div className="agent-card__heading">
                    <h3>{contract.event_type}</h3>
                    <span className="status-pill status-pill--active">
                      v{contract.schema_version}
                    </span>
                  </div>
                  <p>{contract.description}</p>
                  <p className="fine-print">
                    {contract.aggregate_type} →{" "}
                    {contract.consumer_names.join(", ")}
                  </p>
                </article>
              ))}
            </div>
          </section>

          <section className="panel" aria-labelledby="ledger-heading">
            <div className="agent-card__heading">
              <div>
                <p className="eyebrow">SELECTED-BUSINESS LEDGER</p>
                <h2 id="ledger-heading">
                  {dashboard.total_events} durable event
                  {dashboard.total_events === 1 ? "" : "s"}
                </h2>
              </div>
              <nav className="header-actions" aria-label="Delivery filters">
                <Link className="text-link" href="/events">
                  All
                </Link>
                <Link className="text-link" href="/events?status=dead_letter">
                  Dead letter
                </Link>
                <Link className="text-link" href="/events?status=retry_wait">
                  Retrying
                </Link>
                <Link className="text-link" href="/events?status=completed">
                  Completed
                </Link>
              </nav>
            </div>

            {dashboard.events.length === 0 ? (
              <p className="fine-print">
                No real events match this selected-business filter.
              </p>
            ) : (
              <div className="agent-grid">
                {dashboard.events.map((event) => (
                  <article className="agent-card" key={event.id}>
                    <div className="agent-card__heading">
                      <div>
                        <h3>{event.event_type}</h3>
                        <p className="fine-print">
                          {event.aggregate_type}:{event.aggregate_id}
                        </p>
                      </div>
                      <span className="status-pill status-pill--active">
                        v{event.schema_version}
                      </span>
                    </div>
                    <p>Occurred {timestamp(event.occurred_at)} UTC</p>
                    <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                    <p className="fine-print">
                      Event {event.id} · correlation{" "}
                      {event.correlation_id ?? "none"}
                    </p>
                    {event.deliveries.map((delivery) => (
                      <div className="run-card" key={delivery.id}>
                        <div className="agent-card__heading">
                          <strong>{delivery.consumer_name}</strong>
                          <span
                            className={`status-pill status-pill--${
                              delivery.status === "completed"
                                ? "completed"
                                : delivery.status === "dead_letter"
                                  ? "failed"
                                  : "queued"
                            }`}
                          >
                            {delivery.status}
                          </span>
                        </div>
                        <p className="fine-print">
                          Attempts {delivery.attempt_count}/
                          {delivery.max_attempts}
                          {delivery.completed_at
                            ? ` · completed ${timestamp(delivery.completed_at)} UTC`
                            : ""}
                        </p>
                        {delivery.last_error_type ? (
                          <p className="notice notice--error">
                            {delivery.last_error_type}:{" "}
                            {delivery.last_error_message}
                          </p>
                        ) : null}
                        {delivery.status === "dead_letter" ? (
                          <form
                            action={redriveEventDelivery.bind(
                              null,
                              delivery.id,
                              delivery.redrive_count,
                            )}
                          >
                            <button type="submit">Redrive delivery</button>
                          </form>
                        ) : null}
                      </div>
                    ))}
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
