# Architecture Decision Records

| ADR                                                                 | Decision                                                                  | Status   |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------- | -------- |
| [ADR-0001](ADR-0001-owner-operated-v1.md)                           | Owner-operated V1 with future SaaS boundaries                             | Accepted |
| [ADR-0002](ADR-0002-modular-monolith.md)                            | Modular monolith with separated processes                                 | Accepted |
| [ADR-0003](ADR-0003-phase-gated-delivery.md)                        | Strict phase-gated, evidence-based delivery                               | Accepted |
| [ADR-0004](ADR-0004-governed-side-effects.md)                       | Govern all external and risky side effects                                | Accepted |
| [ADR-0005](ADR-0005-rq-worker.md)                                   | Redis Queue for the foundation worker                                     | Accepted |
| [ADR-0006](ADR-0006-portable-container-runtime.md)                  | Portable containers and deferred deployment provider                      | Accepted |
| [ADR-0007](ADR-0007-single-owner-password-auth.md)                  | Single-owner password authentication with opaque sessions                 | Accepted |
| [ADR-0008](ADR-0008-session-selected-business-context.md)           | Session-selected business context and strict operational scoping          | Accepted |
| [ADR-0009](ADR-0009-founder-approved-onboarding-facts.md)           | Resumable onboarding with an explicit founder-approved fact boundary      | Accepted |
| [ADR-0010](ADR-0010-governed-provider-independent-model-gateway.md) | Governed provider-independent model gateway                               | Accepted |
| [ADR-0011](ADR-0011-provenance-first-derived-business-context.md)   | Provenance-first derived business context                                 | Accepted |
| [ADR-0012](ADR-0012-versioned-durable-agent-runtime.md)             | Immutable agent versions with durable worker-owned runs                   | Accepted |
| [ADR-0013](ADR-0013-immutable-versioned-skill-assignments.md)       | Immutable skill versions with exact agent assignments                     | Accepted |
| [ADR-0014](ADR-0014-transactional-task-lifecycle.md)                | Transactional task lifecycle with dependency gates and idempotent retries | Accepted |
| [ADR-0015](ADR-0015-versioned-durable-workflow-coordinator.md)      | Version-pinned durable workflow coordination                              | Accepted |
| [ADR-0016](ADR-0016-execution-time-governance.md)                   | Execution-time governance with immutable policy evidence                  | Accepted |
| [ADR-0017](ADR-0017-transactional-domain-event-delivery.md)         | Transactional domain events with idempotent durable delivery              | Accepted |
| [ADR-0018](ADR-0018-provider-neutral-knowledge-retrieval.md)        | Provider-neutral knowledge ingestion and pgvector retrieval               | Accepted |
| [ADR-0019](ADR-0019-curated-provenance-first-memory.md)             | Curated, provenance-first memory with explicit fact authority             | Accepted |
| [ADR-0020](ADR-0020-traceable-advisory-executive-agents.md)         | Traceable advisory executive agents with no execution authority           | Accepted |
| [ADR-0021](ADR-0021-founder-approved-evidence-linked-strategy.md)   | Founder-approved, evidence-linked business strategy                       | Accepted |
| [ADR-0022](ADR-0022-immutable-founder-approved-product-offers.md)   | Immutable, founder-approved product and offer portfolio versions          | Accepted |
| [ADR-0023](ADR-0023-founder-approved-evidence-linked-brand-system.md) | Founder-approved, evidence-linked brand system                          | Accepted |
| [ADR-0024](ADR-0024-specification-before-code-generation.md)        | Founder-approved website specification before code generation             | Accepted |

Future decisions should use the next sequential number and record context, decision, consequences, and supersession links.
