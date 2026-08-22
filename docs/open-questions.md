# Foundora Open Questions

These questions do not block Phase 00. They are intentionally routed to the phase in which the answer becomes necessary, avoiding premature decisions.

| Decision needed | Needed by | Current safe default |
|---|---:|---|
| Which founder-owned business will be the first real launch? | Required for Phase 61 | Keep the business registry and onboarding generic; do not seed demo assumptions |
| Which production deployment target should be selected? | Phase 59 | Continue with provider-independent Linux containers and environment-based configuration |
| Which search provider is preferred and what research budget is acceptable? | Phase 16 | No external research claims until a provider/tool is configured |
| Which object-storage provider should back production assets? | Phase 13/26 and Phase 59 | Use an abstraction; local development storage only when explicitly labeled |
| Which preview/deployment and DNS providers are preferred? | Phase 24/25 | Local build/preview only; never claim deployment or DNS state |
| Which email, social, advertising, analytics, CRM, and messaging providers are in scope? | Relevant provider phases | Planning/drafts only until adapter, credentials, permission, policy, and tests exist |
| What monetary limits apply per action/day/provider? | Phase 11 and provider phases | Zero autonomous spend; explicit approval for R4 |
| What retention, backup, privacy, and jurisdictional requirements apply to real business/customer data? | Before Phase 13 and Phase 33 | Minimize data, store provenance, exclude secrets, and avoid ingesting regulated data without a policy |
| Which production domain and subdomain conventions should be used? | Phase 25/59 | None selected |

## Resolved in Phase 01

1. Docker Desktop with Docker Compose is the required local runtime and was verified successfully.
2. RQ is the Redis-backed foundation worker adapter; scheduler behavior remains deferred.
3. No deployment environment is selected. Core architecture remains provider-independent until Phase 59.
4. Phase 02 uses a server-provisioned owner password hashed with Argon2id and revocable opaque sessions. Passkeys and external identity remain replaceable future options, not current dependencies.
5. Phase 03 stores the selected business on each owner session. Operational routes never accept an arbitrary business ID; only the explicit switch operation does.
6. Phase 04 keeps mutable onboarding drafts separate from versioned approved profiles. No draft or future AI suggestion becomes fact without explicit founder approval.
7. Connected services entered during onboarding are founder declarations only. Provider credential validation and real connection state belong to their later provider phases.
8. Phase 05 starts with OpenAI as primary, Gemini then Anthropic as fallbacks for
   explicitly standard-sensitivity requests. The founder configured OpenAI and
   Gemini locally; `gpt-4o-mini` is the tested OpenAI default, and Anthropic
   remains cleanly disabled until a key is supplied.
   Per-request defaults are 512 output tokens, 8,192 total tokens, and $0.10
   estimated cost, with a hard 4,096 output-token ceiling. Later policy phases may
   add action/day/provider budgets without bypassing these gateway limits.
9. Phase 06 derives business context on demand rather than persisting a duplicate
   snapshot. It reads only live workspace records, founder-approved onboarding
   facts, and current operational goals for the session-selected business.
10. Context selection uses fixed source priority and a provider-independent upper
    bound of one token per UTF-8 byte. Completed goals are stale, cancelled goals
    are invalidated, and unimplemented source domains are reported unavailable.
11. Phase 07 stores reusable agent identity separately from immutable versions and
    pins every run to a version. The first agent is R0, manual-run-only, read-only,
    and initially had empty tool and skill permissions.
12. Agent runs snapshot approved selected-business context at enqueue time, execute
    only in the existing worker through the governed model gateway, and persist
    honest terminal output or failure plus directly linked usage attempts.
13. Cancellation is cooperative at the durable boundary: queued work is skipped,
    and a late provider result cannot overwrite a run already marked cancelled.
    Tool waits and approval waits remain lifecycle-compatible but unused until
    their authorized phases.
14. Phase 08 stores skill identity separately from immutable versions. Compatibility
    supports discovery but never grants authority; an exact immutable agent-version
    to skill-version assignment is required at enqueue and re-checked by the worker.
15. The three initial skills are R0 and tool-free. Only the business-context summary
    skill is assigned to runtime agent version 2. Skill workflow fields are
    declarative contracts, not the Phase 10 executable workflow engine.

Other questions can remain open until their named phase.
