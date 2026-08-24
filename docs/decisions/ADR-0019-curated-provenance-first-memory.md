# ADR-0019: Curated, provenance-first memory

Status: Accepted

## Context

Phase 14 requires seven distinct memory types, durable-memory proposals, founder
or automatic acceptance policy, duplicate merging, stale-memory invalidation,
retrieval filters, and visible provenance. The system must never convert an
assumption into an approved business fact or persist secrets as memory.

## Decision

- Working, episodic, semantic, decision, preference, workflow, and evaluation
  memory remain explicit types. Each type permits only its code-reviewed
  epistemic statuses; semantic assumptions and semantic facts remain distinct.
- A deterministic `MemoryService` is the curator boundary. It normalizes and
  validates proposals, resolves system provenance below the selected-business
  boundary, rejects credential-shaped content, and records a pending proposal
  before durable acceptance.
- Founder review is the default. Semantic facts, decisions, and preferences
  always require explicit founder acceptance. Per-business automatic acceptance
  is opt-in and limited to working, episodic, workflow, and evaluation memory
  with verified internal provenance and a founder-set confidence floor.
- Exact normalized duplicates merge into one active record. Each accepted or
  merged proposal creates an immutable content revision and provenance entry.
- Working memory requires an existing selected-business execution, an execution
  scope, and expiry within seven days. Expired, invalidated, and unrelated
  working records are excluded beneath retrieval.
- Active memory enters Business Brain as a distinct source. Its authority names
  the epistemic status; only founder-accepted facts use
  `founder_approved_fact`. Provenance remains in the compiled context.
- Proposal, acceptance, merge, and invalidation events share the transactional
  PostgreSQL outbox. No provider or model call is introduced.

## Consequences

The founder can distinguish hypotheses from facts and audit exactly why a memory
exists. Automatic curation remains narrow and reversible. Secret detection is a
defense-in-depth guard, not a substitute for a production data-classification or
retention policy. Semantic similarity merging, autonomous extraction, and
production retention automation require later explicit phases.
