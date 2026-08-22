# ADR-0010: Governed provider-independent model gateway

## Status

Accepted on 2026-08-22.

## Context

Phase 05 requires real OpenAI, Gemini, and optionally Anthropic access while the
deployment provider remains undecided. Later agents and workflows need one stable
contract for routing, streaming, structured output, usage, and failure handling.
Provider credentials and model responses must not become business facts, leak into
the browser, or bypass budget and sensitivity policy.

## Decision

- Core callers use Foundora request, response, and stream event types. Thin native
  HTTP adapters translate those types to OpenAI Responses, Gemini
  generate-content, and Anthropic Messages APIs.
- Models and rates are an allow-listed, code-reviewed registry. Primary provider,
  fallback order, and task routes are configurable only to registry entries.
- Missing environment credentials disable an adapter honestly. Validation is an
  explicit network operation with a durable sanitized outcome.
- Cross-provider fallback is opt-in for standard content and prohibited for
  sensitive content. Retry is limited to classified transient failures. Streaming
  cannot fallback after output starts.
- Each request declares output, total-token, and estimated-cost limits. Conservative
  preflight estimates stop over-budget requests before execution; retries and
  fallback consume the same operation budget.
- Durable attempt records are scoped to the selected business and contain routing,
  usage, estimated cost, latency, and sanitized failure metadata. Prompts, output,
  API keys, and raw provider bodies are deliberately excluded.
- Provider base URLs are fixed in adapters, and no cloud hosting or deployment
  provider is selected by this decision.

## Consequences

Callers can change provider or model routing without importing provider SDKs, and
Foundora can report actual metered usage without storing sensitive content.
Provider feature differences remain isolated in adapters. Registry pricing must be
reviewed when providers change rates; estimates are governance metadata, not an
invoice. Business-brain context assembly, agent execution, and autonomous policy
remain later phases and cannot call providers outside this gateway.
