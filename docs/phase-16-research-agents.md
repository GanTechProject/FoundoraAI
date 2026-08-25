# Phase 16 — Research Agents

Status: **COMPLETE**

## Delivered scope

- Immutable `market-research@1`, `competitor-intelligence@1`, and
  `customer-research@1` registry contracts.
- A provider-neutral `SearchProvider` protocol with business-scoped requests
  and normalized evidence containing a durable evidence ID, source, source
  title, retrieval date and timestamp, excerpt, and content SHA-256.
- `RegisteredKnowledgeSearchProvider`, the default adapter over active Phase 13
  knowledge. It searches only founder-registered evidence for the selected
  business and performs no public-web or external-provider call.
- Pre-runtime evidence retrieval that pins the exact provider, query, sources,
  dates, excerpts, and hashes into the immutable agent-run input before a model
  is called.
- Protected, CSRF-checked `POST /agents/research/search` evidence preview for
  deterministic inspection of the same provider boundary without queueing a
  model run.
- Source-backed findings for market trends and demand signals; competitor
  positioning, pricing, features, strengths, weaknesses, and whitespace; and
  customer ICP, personas, jobs-to-be-done, pain points, buying triggers, and
  objections.
- Protected `/agents` forms for explicit research queries and a run inspector
  showing the exact evidence trace and validation state.

## Anti-invention boundary

Every finding carries a claim, support flag, confidence, limitations, and a
source list containing exact evidence IDs, source locations, and retrieval
dates. A supported claim must also be an extractive statement present in one of
its cited excerpts. Runtime semantic validation rejects unknown or altered
citations, invented supported claims, mismatched query/context identity,
role-incompatible categories, duplicate finding IDs, supported claims without
sources, unsupported claims that claim a source, and unsupported claims without
limitations.

Competitor findings add a stricter rule: a supported competitor subject must be
named in its cited source title or excerpt. An unsupported competitor finding
must use `unknown` as its subject, so an uncited name cannot enter output merely
by being labeled uncertain. Output status is derived from whether any finding
is actually supported; an evidence-empty result must state overall limitations.

## Provider and authority boundary

`SearchProvider` is an interface, not a vendor selection. No search vendor,
deployment vendor, or provider-specific architecture is introduced. A future
adapter can implement the same request/evidence contract without changing the
research-agent runtime or output validation.

All three agents remain R0 and `manual_advisory_only`, with no allowed tools or
assigned skills. Search is a host-mediated, read-only evidence acquisition step
that completes before model execution; the model cannot invoke it. The agents
cannot perform recurring monitoring, contact people, spend, mutate knowledge or
memory, create tasks or workflows, approve actions, or take any external side
effect. Explicit agent runs still use the provider-independent model gateway and
fail honestly when the configured model provider is unavailable.

## Durable model

Migration `20260825_16` adds no new table. It seeds the three identities and
their immutable version-one contracts in the existing `agents` and
`agent_versions` tables. Search evidence and validated research output live in
the existing immutable run record, preserving exact version, context, source,
model-operation, usage, lifecycle, and failure traceability.

## Acceptance evidence

Unit and runtime tests prove provider normalization, exact source/date matching,
unsupported-claim flagging, specialist category boundaries, competitor-name
anti-invention checks, prompt constraints, honest semantic failure, and API run
trace exposure. Deterministic Docker smoke checks prove all three immutable
contracts, CSRF enforcement, selected-business search against real indexed
knowledge, durable citations, protected UI rendering, migration state, and
healthy services without making a model-provider call. Final deterministic
evidence includes 126 API tests, both web tests, strict Python and TypeScript
checks, production builds, a fresh upgrade/downgrade/re-upgrade round trip at
`20260825_16`, and five healthy primary services.

The isolated smoke suite reaches and passes the explicit Phase 16 contract,
SearchProvider, citation, CSRF, and protected-UI checkpoint. Its later legacy
live agent regression still stops honestly because the configured OpenAI
credential returns 401 and Gemini agent generation returns 429 quota responses.
An earlier capped gateway fallback reached Gemini successfully, so this is
external credential/quota state rather than a Phase 16 search or research
contract failure; no provider success is fabricated.

Phase 17 business strategy is not implemented. Phase 16 stops here.
