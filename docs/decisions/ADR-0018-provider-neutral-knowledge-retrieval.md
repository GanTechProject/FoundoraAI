# ADR-0018 — Provider-neutral knowledge retrieval

- Status: Accepted
- Date: 2026-08-25

## Context

Phase 13 requires uploaded documents to become retrievable with preserved
citations and explicit invalidation. The production object-storage provider and
any future hosted embedding provider remain undecided. Binding ingestion to a
cloud SDK or model vendor would violate the portable modular-monolith boundary.

## Decision

- Knowledge source, document, chunk, provenance, status, and vector metadata are
  durable selected-business PostgreSQL records.
- Original files cross a `KnowledgeStorage` interface. Local Docker development
  uses a named volume and content-addressed keys; a production object-storage
  adapter remains a later configuration decision.
- Extraction v1 accepts bounded UTF-8 `.txt`, `.md`, `.json`, and `.csv` files.
  Unsupported types, invalid UTF-8, null bytes, malformed JSON, empty content,
  and configured size-limit violations fail without a success record.
- `foundora.local-feature-hash.v1` is a deterministic 256-dimensional local
  embedding adapter. It makes no network or model-provider call and records its
  exact model identifier with every document and chunk.
- PostgreSQL 18.6 uses the open-source pgvector 0.8.6 extension. Chunk vectors
  use `vector(256)` and an HNSW cosine index; the Python adapter is pinned at
  pgvector 0.5.0.
- Retrieval always scopes active sources and indexed documents to the session's
  selected business. Results carry source, document, chunk, character-offset,
  timestamp, URI, and SHA-256 citation evidence.
- Source/document invalidation is optimistic and durable. Invalidated records
  remain inspectable but are excluded below the retrieval boundary.
- Knowledge remains founder-registered evidence, not an approved business fact
  or durable memory. Phase 14 memory semantics are not introduced.

## Consequences

The phase is usable without external credentials or usage charges and can later
swap storage or embedding adapters without rewriting domain contracts. The
local lexical embedding is intentionally modest; a future adapter may improve
semantic quality only with a migration/version strategy. Production retention,
privacy, backup, and object-storage choices remain explicit deployment inputs.
