# Foundora Open Questions

These questions do not block Phase 00. They are intentionally routed to the phase in which the answer becomes necessary, avoiding premature decisions.

| Decision needed | Needed by | Current safe default |
|---|---:|---|
| Which founder-owned business will be the first real launch? | Required for Phase 61 | Keep the business registry and onboarding generic; do not seed demo assumptions |
| Which production deployment target should be selected? | Phase 59 | Continue with provider-independent Linux containers and environment-based configuration |
| Which AI providers and budgets will the founder configure first? | Phase 05 | All providers disabled without valid credentials; no mock AI output |
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

Other questions can remain open until their named phase.
