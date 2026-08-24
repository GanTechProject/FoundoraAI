# Phase 13 — Knowledge Ingestion

Status: COMPLETE

## Delivered

- protected selected-business source registration with typed provenance,
  bounded JSON metadata, optional HTTP(S) citation URI, revision, and status;
- bounded raw file upload through the authenticated API and local
  object-storage abstraction;
- explicit UTF-8 text, Markdown, JSON, and CSV extraction contract;
- paragraph-aware overlapping chunks with exact character offsets, content
  hashes, and conservative token estimates;
- versioned deterministic local embeddings stored as pgvector `vector(256)`;
- database-native cosine retrieval through an HNSW index;
- citations preserving source/document/chunk identity, source URI, filename,
  offsets, timestamps, and SHA-256 fingerprints;
- optimistic source and document invalidation, with invalidated material
  excluded by the database query itself;
- optional explicit knowledge retrieval in the Business Brain, where evidence
  remains identified as founder-registered knowledge rather than approved fact;
- transactional `knowledge.source_registered`,
  `knowledge.document_indexed`, `knowledge.document_invalidated`, and
  `knowledge.source_invalidated` domain events;
- a real `/knowledge` UI for registration, upload, retrieval, citation review,
  and invalidation.

## Portability boundary

The `KnowledgeStorage` protocol owns file persistence. Docker development uses
the `knowledge_data` named volume at `/var/lib/foundora/knowledge`; this is
explicitly local storage, not a production object-store claim. Embeddings cross
an `EmbeddingAdapter`, and v1 uses `foundora.local-feature-hash.v1` without a
provider credential or network request.

PostgreSQL is the retrieval authority. The Compose database image pins pgvector
0.8.6 on PostgreSQL 18.6 by immutable digest, and the API pins pgvector-python
0.5.0. No cloud, model, or storage vendor becomes a domain dependency.

## Ingestion bounds and failure behavior

- maximum upload: 5,242,880 bytes by default;
- maximum extracted text: 1,000,000 characters by default;
- supported extensions/media types: `.txt`, `.md`, `.json`, and `.csv` with
  their declared text media types;
- filenames cannot contain paths;
- unsupported, empty, invalid UTF-8, null-containing, and malformed JSON files
  return an explicit client error;
- duplicate content under one source is rejected;
- a failed database transaction removes the just-written local object;
- no catch path returns an indexed status unless source, document, chunks,
  vectors, and event delivery records committed together.

The local file type contract deliberately excludes PDF, office documents,
images, OCR, archives, remote fetching, and crawling. Those capabilities require
reviewed extractors and are not fabricated by Phase 13.

## Retrieval and invalidation invariants

- every query resolves the authenticated session's selected business;
- only `active` sources and `indexed` documents can reach vector search;
- composite foreign keys keep chunk, document, source, and business scope
  consistent in PostgreSQL;
- the embedding model identifier is checked at retrieval;
- invalidation retains provenance and original evidence while excluding it from
  search and Business Brain context;
- source invalidation cascades logical invalidation to its active documents;
- citations are returned with every hit and shown in the protected UI.

## Verification

Phase acceptance is covered by unit/API tests and the Docker smoke suite:

- all 96 API tests and both web tests pass;
- valid extraction, chunk offsets, deterministic embeddings, cosine ranking,
  citation preservation, local-storage round trip, auth, and malformed files;
- a fresh migration to `20260825_13` with the vector extension and HNSW index;
- real source registration and file upload;
- uploaded content retrieval with its original citation;
- duplicate and malformed upload rejection;
- document/source invalidation followed by retrieval exclusion;
- selected-business read/mutation isolation;
- cited knowledge entering Business Brain only through an explicit query;
- all nine domain-event contracts dispatched exactly once;
- protected `/knowledge` rendering from real API state.

Phase 14 memory types, curation, acceptance policy, duplicate-memory merging, and
memory expiry are not implemented. Phase 13 stops here.
