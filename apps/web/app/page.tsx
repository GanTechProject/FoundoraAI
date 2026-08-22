import {
  isReadinessPayload,
  toServiceViews,
  type ServiceView,
} from "../lib/readiness";

export const dynamic = "force-dynamic";

async function loadServices(): Promise<{
  services: ServiceView[];
  apiStatus: "up" | "down";
}> {
  const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

  try {
    const response = await fetch(`${apiUrl}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    const payload: unknown = await response.json();
    if (!isReadinessPayload(payload))
      throw new Error("API returned an invalid readiness payload");

    return {
      apiStatus: response.ok && payload.status === "ready" ? "up" : "down",
      services: toServiceViews(payload),
    };
  } catch {
    return {
      apiStatus: "down",
      services: [
        {
          name: "postgresql",
          status: "down",
          detail: "Readiness could not be verified",
        },
        {
          name: "redis",
          status: "down",
          detail: "Readiness could not be verified",
        },
      ],
    };
  }
}

export default async function Home() {
  const { apiStatus, services } = await loadServices();
  const allServices = [
    {
      name: "api",
      status: apiStatus,
      detail: apiStatus === "up" ? "Ready" : "Unavailable",
    },
    ...services,
  ];

  return (
    <main>
      <section className="hero" aria-labelledby="page-title">
        <p className="eyebrow">FOUNDORA / FOUNDATION</p>
        <h1 id="page-title">The operating layer for building a business.</h1>
        <p className="lede">
          Phase 01 establishes the portable web, API, database, cache, and
          worker runtime. Product capabilities arrive only in their authorized
          phases.
        </p>
      </section>

      <section className="status-panel" aria-labelledby="runtime-heading">
        <div>
          <p className="eyebrow">LIVE READINESS</p>
          <h2 id="runtime-heading">Runtime services</h2>
        </div>
        <ul>
          {allServices.map((service) => (
            <li key={service.name}>
              <span
                className={`indicator indicator--${service.status}`}
                aria-hidden="true"
              />
              <span className="service-name">{service.name}</span>
              <span className="service-detail">{service.detail}</span>
            </li>
          ))}
        </ul>
        <p className="disclaimer">
          These states come from the API readiness check. No future product data
          or provider state is simulated.
        </p>
      </section>
    </main>
  );
}
