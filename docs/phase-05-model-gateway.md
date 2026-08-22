# Phase 05 - Model Gateway

Status date: 2026-08-22

## Scope delivered

- a provider-independent FastAPI model gateway with OpenAI Responses, Gemini
  generate-content, and Anthropic Messages adapters;
- a governed model registry with exact provider model identifiers, streaming and
  structured-output capabilities, and a dated pricing snapshot;
- default, fallback, and JSON-configured task routing without provider SDK types
  entering the application contract;
- explicit configuration validation, clean missing-key disablement, bounded
  timeouts, retryable failure classification, capped exponential retry, and
  standard-sensitivity-only cross-provider fallback;
- request token/output/cost preflight and shared operation-level accounting across
  retry and fallback attempts;
- non-streaming, server-sent-event streaming, and strict JSON-schema requests;
- business-scoped durable attempt records for tokens, estimated cost, latency,
  retry/fallback lineage, and sanitized errors;
- protected API routes and an owner-facing `/settings/ai` dashboard;
- migration `20260822_05` for gateway attempts and provider validations.

## Security and portability invariants

- Provider secrets are read only on the server from environment variables through
  `SecretStr`. Keys, prompts, model output, and raw provider error bodies are not
  persisted or returned by configuration endpoints.
- A missing key reports the provider as disabled. It never enables placeholder or
  fabricated output.
- Provider endpoints are fixed inside adapters. Core configuration cannot redirect
  outbound model traffic to an arbitrary URL.
- Fallback is opt-in and rejected for sensitive requests. A stream never changes
  provider after its first emitted delta.
- All attempts in one operation share the declared token and cost budgets. Billed
  usage remains recorded even when structured output is invalid or a post-response
  budget check fails.
- The implementation uses portable HTTP and application interfaces. It introduces
  no deployment-provider architecture.
- Gemini requests use the model-supported `MINIMAL` thinking level so bounded
  output budgets reserve capacity for the requested answer instead of silently
  consuming a short response entirely on internal reasoning.

## Governed registry snapshot

Rates are stored as integer micro-US-dollars and were reviewed against provider
documentation on 2026-08-22:

| Provider | Model | Input / 1M tokens | Output / 1M tokens |
|---|---|---:|---:|
| OpenAI | `gpt-5.6-luna` | $0.20 | $1.20 |
| Gemini | `gemini-3.6-flash` | $0.75 | $3.75 |
| Anthropic | `claude-haiku-4-5-20251001` | $1.00 | $5.00 |

The Gemini rate is introductory through 2026-12-31 and must be reviewed before
that date. Model or price changes require a registry/code review rather than an
untracked environment override.

## Acceptance evidence

`./scripts/verify.ps1` runs backend and frontend formatting, linting, strict type
checking, unit tests, production builds, migration validation, container health,
and the isolated Docker smoke suite. Unit tests cover all three native request
formats, structured output, streaming usage, missing keys, fallback, preflight
budgets, and failed structured-output accounting.

The smoke suite checks OpenAI and Gemini against their real configured model
endpoints. On the acceptance run, Gemini validated successfully; the supplied
OpenAI credential was rejected with HTTP 401 and its sanitized invalid outcome was
persisted. The suite proves Anthropic is cleanly disabled without a key, then makes
one fixed non-sensitive generation with a 32-token ceiling and a $0.002 cost
ceiling. The invalid OpenAI primary falls back to Gemini, and the successful usage
row is verified in PostgreSQL. The suite also rejects unauthenticated, missing-CSRF,
under-budgeted, and sensitive-fallback requests and renders the protected gateway
dashboard. Temporary state is removed in `finally`; real keys are neither printed
nor persisted.

Phase 06 business-brain behavior is documented separately in
`docs/phase-06-business-brain.md`; it consumes no provider directly and remains
behind the Phase 05 gateway boundary for future model calls.
