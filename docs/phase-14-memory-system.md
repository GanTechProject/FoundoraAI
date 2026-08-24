# Phase 14 — Memory System

Status: **COMPLETE**

## Delivered scope

- Seven selected-business memory types: working, episodic, semantic, decision,
  preference, workflow, and evaluation.
- A deterministic curator proposal boundary with normalized content, strict
  type/epistemic mappings, bounded fields, source validation, and conservative
  credential/secret rejection.
- A founder-safe acceptance policy. The default requires founder review;
  automatic acceptance is opt-in and restricted to verified operational memory
  types above a configurable confidence floor.
- A hard semantic-fact invariant: facts can be accepted only through an explicit
  founder decision. Assumptions remain labeled and enter context only with
  `curated_assumption` authority.
- Exact duplicate merging into one durable record with immutable revision and
  provenance rows for every accepted proposal.
- Optimistic founder rejection and stale-memory invalidation. Invalidated and
  expired records are excluded below retrieval.
- Execution-scoped working memory with mandatory expiry no more than seven days.
- Retrieval filters for type, epistemic status, text, lifecycle, and execution;
  Business Brain excludes unscoped working memory.
- Protected `/memory` API and owner UI for policy, proposals, founder decisions,
  provenance inspection, filtering, and invalidation.
- Transactional `memory.proposed`, `memory.accepted`, `memory.merged`, and
  `memory.invalidated` domain events.

## Durable model

Migration `20260825_14` adds `memory_policies`, `memory_proposals`,
`memory_records`, `memory_revisions`, and `memory_provenance`. Database
constraints repeat application invariants for type, epistemic status, working
scope, fact acceptance, source identity, confidence, and revision bounds.

## Acceptance evidence

The deterministic quality and smoke gates verify explicit assumption/fact
authority, founder and safe automatic acceptance, exact duplicate merging,
revisioned visible provenance, clean secret rejection, expiry/invalidation
exclusion, Business Brain integration, selected-business isolation, all memory
events, a fresh migration, protected UI rendering, and the complete regression
suite.

Final deterministic evidence includes 111 passing API tests, both web tests,
strict API/web formatting, lint and typing, the production Next.js build, and
the isolated full-system smoke suite.

Phase 15 executive agents are not implemented. Phase 14 stops here.
