FOUNDORA — COMPLETE MASTER BUILD SPECIFICATION
AI BUSINESS LAUNCH & AUTONOMOUS OPERATING SYSTEM
Version 2.0 — Single-User / Owner-Operated Product First
========================================================

DOCUMENT PURPOSE
----------------
This is the authoritative build prompt for developing Foundora as a complete AI-powered Business Launch & Operating System.

CURRENT PRODUCT INTENT:
- Foundora is NOT being built as a public multi-tenant SaaS in this version.
- It is first being built as a complete owner-operated application for launching, building, growing, monitoring, and operating real businesses.
- The architecture MUST remain modular enough that SaaS/multi-tenancy can be added later without rewriting the core business, agent, workflow, tool, memory, or provider systems.
- Do NOT spend development effort now on enterprise SSO, public subscription plans, organization billing, thousands of tenant environments, Kubernetes, multi-region infrastructure, or other SaaS-scale concerns unless they are required for the owner-operated product.
- Do NOT remove clean extension points that would make future SaaS conversion possible.

PRIMARY PRODUCT PROMISE
-----------------------
A founder can give Foundora a business idea, an existing business, a goal, or a problem.

Foundora must be capable of:
1. understanding the business;
2. researching the market;
3. validating assumptions with evidence;
4. identifying competitors;
5. defining target customers;
6. constructing the business model;
7. designing offers/products/services;
8. creating brand strategy;
9. creating business plans and launch plans;
10. creating and maintaining a website;
11. generating marketing strategy and assets;
12. supporting SEO;
13. identifying and managing leads;
14. supporting sales workflows;
15. managing customers/CRM data;
16. assisting customer support and success;
17. assisting operational workflows;
18. monitoring business KPIs;
19. assisting financial analysis;
20. discovering problems/opportunities;
21. proposing work autonomously;
22. executing permitted work through tools;
23. requesting human approval for risky/external actions;
24. measuring outcomes;
25. retaining approved business knowledge and lessons;
26. continuously improving future plans.

Foundora is not a collection of unrelated chatbots.
It is one coordinated Business Operating System.

======================================================================
SECTION A — NON-NEGOTIABLE ANTI-HALLUCINATION BUILD CONTRACT
======================================================================

THE CODING AGENT MUST FOLLOW THESE RULES DURING EVERY PHASE.

A1. REPOSITORY TRUTH
- Inspect the actual repository before modifying anything.
- Never describe a file, module, database table, endpoint, component, test, worker, integration, migration, or configuration as existing unless it has been verified.
- Never infer implementation from filenames alone.
- Never claim a phase is complete because code was generated.
- Verify wiring and runtime behavior.

A2. NO FAKE PRODUCT BEHAVIOR
- Production UI must never use invented business metrics.
- Do not use mock responses to make unfinished integrations look operational.
- Do not silently catch failures and return fabricated success.
- Do not display "Connected", "Deployed", "Sent", "Published", "Paid", "Running", or "Completed" unless real state supports it.
- Development fixtures are allowed only when explicitly labelled and isolated from production behavior.

A3. NO SECRET INVENTION
- Never invent API keys, credentials, OAuth tokens, webhook secrets, email addresses, provider IDs, domain records, payment IDs, or external responses.
- Secrets must come from environment variables or a secrets provider.
- Create .env.example using variable names and descriptions only.
- Never commit secrets.
- Never expose provider secrets to the frontend.

A4. THIRD-PARTY API RULE
When implementing OpenAI, Gemini, Anthropic/Claude, email, search, deployment, DNS, payments, social, advertising, analytics, CRM, or any external provider:
- verify current official provider documentation;
- implement through an adapter;
- validate credentials;
- handle timeouts;
- handle rate limits;
- handle provider errors;
- implement retry only when safe;
- implement idempotency for external side effects;
- store provider request/reference IDs where useful;
- never fabricate provider success.

A5. PHASE BOUNDARIES
- Implement exactly ONE phase at a time.
- Do not quietly start future phases.
- Future-facing interfaces may be created only when required by the current phase.
- At phase end, STOP.
- Continue only after explicit human instruction.

A6. DEFINITION OF DONE
A feature is DONE only when:
- implemented;
- integrated;
- persisted when required;
- authorized;
- error-handled;
- tested;
- observable;
- documented;
- accessible through the intended UI/API;
- manually smoke-tested when practical.

A7. FAILURE BEHAVIOR
If blocked:
- preserve the working system;
- document the blocker;
- show exact evidence;
- mark phase PARTIAL or BLOCKED;
- do not invent a workaround that changes product requirements.

A8. CHANGE DISCIPLINE
Before changes:
- inspect relevant source;
- inspect tests;
- inspect migrations;
- inspect interfaces;
- inspect dependencies.

After changes:
- run formatter;
- run lint;
- run type checking;
- run relevant unit tests;
- run relevant integration tests;
- run build;
- run smoke tests;
- inspect git diff;
- scan for secrets;
- update documentation.

======================================================================
SECTION B — PRODUCT ARCHITECTURE
======================================================================

TARGET LOGICAL ARCHITECTURE

Founder
  |
  v
Foundora UI
  |
  v
Foundora API
  |
  +--> Business Brain / Context
  |
  +--> Goal & Task Engine
  |
  +--> Autonomous Orchestrator
  |       |
  |       +--> Agent Registry
  |       +--> Workflow Engine
  |       +--> Skills Registry
  |       +--> Memory Retrieval
  |
  +--> Governance
  |       |
  |       +--> Policy Engine
  |       +--> Approval Engine
  |       +--> Risk Controls
  |       +--> Budgets
  |
  +--> Tool Runtime
  |       |
  |       +--> Internal Tools
  |       +--> MCP Tools
  |       +--> Provider Adapters
  |
  +--> Event Bus
  |
  +--> Scheduler
  |
  +--> Observability
  |
  +--> PostgreSQL / Redis / Object Storage

AUTONOMOUS BUSINESS LOOP

OBSERVE
  ->
UNDERSTAND
  ->
DETECT PROBLEM / OPPORTUNITY
  ->
PRIORITIZE
  ->
PLAN
  ->
CREATE TASKS / WORKFLOW
  ->
SELECT AGENTS + SKILLS + TOOLS
  ->
RISK CHECK
  ->
APPROVAL IF REQUIRED
  ->
EXECUTE
  ->
VERIFY
  ->
MEASURE OUTCOME
  ->
STORE LEARNING
  ->
REPLAN

IMPORTANT:
The autonomous loop is a system capability, NOT a single omnipotent agent.

======================================================================
SECTION C — RECOMMENDED TECHNOLOGY BASELINE
======================================================================

Frontend
- Next.js
- React
- TypeScript
- accessible component architecture
- responsive UI

Backend
- Python
- FastAPI
- Pydantic
- SQLAlchemy or an equivalent mature ORM
- Alembic

Data
- PostgreSQL
- Redis
- object-storage abstraction
- PostgreSQL pgvector initially if vector search is required

AI
- Provider-independent Model Gateway
- OpenAI adapter
- Google Gemini adapter
- Anthropic/Claude adapter when credentials are supplied
- LangGraph or equivalent graph/state-machine orchestration where it adds value

Workers
- durable background queue
- dedicated worker process
- scheduler process
- sandbox workers for generated code

Development
- Docker
- Docker Compose
- Git
- CI pipeline

Do not introduce Kubernetes during initial product development unless actual requirements prove it necessary.

======================================================================
SECTION D — PROVIDER-INDEPENDENT ARCHITECTURE
======================================================================

AI PROVIDERS
Foundora must support a provider registry.

Conceptual ModelProvider interface:
- validate_configuration()
- list_supported_models()
- generate_text()
- generate_structured()
- stream()
- embed()
- analyze_image() where supported
- calculate_or_record_usage()

Initial adapters:
- OpenAI
- Gemini
- Claude/Anthropic

Configuration must allow:
- primary provider;
- fallback provider;
- task-specific provider;
- task-specific model;
- maximum retries;
- timeout;
- token budget;
- monetary budget where estimable.

Never automatically send sensitive information to a fallback provider unless policy permits it.

OTHER PROVIDER INTERFACES
Design adapters for:
- SearchProvider
- EmailProvider
- StorageProvider
- DeploymentProvider
- DNSProvider
- PaymentProvider
- ImageGenerationProvider
- SocialProvider
- AdvertisingProvider
- AnalyticsProvider
- CRMProvider
- MessagingProvider

Not all adapters must be implemented immediately.
The interfaces must emerge when their relevant phase begins.

======================================================================
SECTION E — COMPLETE AUTONOMOUS AGENT ORGANIZATION
======================================================================

DO NOT create 30 isolated chatbot applications.

Agents share:
- business identity;
- approved business knowledge;
- goals;
- policies;
- memory;
- event history;
- task system;
- tools;
- workflows;
- approval system.

E1. EXECUTIVE ORCHESTRATION

1. Founder / CEO Agent
Purpose:
- understand founder goals;
- translate goals into strategic objectives;
- coordinate specialist agents;
- resolve cross-functional priorities;
- propose next-best actions;
- never directly bypass governance.

2. Planning / Chief-of-Staff Agent
Purpose:
- convert objectives into plans;
- decompose plans into tasks;
- identify dependencies;
- assign candidate agents;
- track plan progress.

E2. DISCOVERY & STRATEGY

3. Market Research Agent
- market research;
- trends;
- demand signals;
- market evidence;
- source-backed findings.

4. Competitor Intelligence Agent
- discover competitors;
- compare positioning;
- pricing;
- features/services;
- strengths/weaknesses;
- whitespace;
- recurring monitoring when enabled.

5. Customer Research Agent
- ICP;
- personas;
- jobs-to-be-done;
- pain points;
- buying triggers;
- objections.

6. Business Strategist Agent
- business model;
- value proposition;
- differentiation;
- pricing strategy;
- go-to-market;
- launch roadmap.

E3. PRODUCT / BRAND / BUILD

7. Product & Offer Agent
- product/service definitions;
- packages;
- feature/benefit structure;
- offer architecture;
- pricing recommendations.

8. Brand Strategist Agent
- positioning;
- brand voice;
- naming analysis;
- messaging;
- tagline;
- visual direction;
- brand guidelines.

9. Website / Coding Agent
- website specifications;
- implementation;
- modifications;
- tests;
- accessibility;
- performance;
- technical SEO;
- cannot deploy directly without deployment workflow.

10. Creative Agent
- image briefs;
- visual assets;
- ad creative;
- social creative;
- website imagery;
- provider dependent.

11. Deployment Agent
- build;
- preview;
- deployment;
- status;
- rollback;
- domain linkage through approved tools.

E4. GROWTH

12. Marketing Strategist Agent
- channel strategy;
- campaign planning;
- launch calendar;
- funnel design;
- campaign objectives.

13. SEO Agent
- keyword research;
- search intent;
- technical SEO;
- content opportunities;
- on-page optimization;
- internal linking;
- monitoring.

14. Content Agent
- website copy;
- blog;
- landing pages;
- newsletters;
- social copy;
- campaign copy;
- content calendar.

15. Social Media Agent
- channel plans;
- posts;
- schedules;
- engagement recommendations;
- publishing only through authorized provider tools.

16. Email Marketing Agent
- newsletters;
- nurture sequences;
- campaigns;
- segmentation recommendations;
- sending only through authorized email tools.

17. Advertising Agent
- campaign structure;
- audiences;
- creatives;
- budgets;
- performance analysis;
- NEVER spend money or change budgets beyond policy without approval.

E5. REVENUE & CUSTOMER

18. Lead Generation Agent
- lead criteria;
- lead discovery using authorized sources;
- enrichment through permitted services;
- lead scoring;
- never fabricate contacts.

19. Sales Agent
- qualification;
- outreach drafts;
- follow-ups;
- proposal support;
- pipeline actions;
- external communication requires policy/approval.

20. CRM Agent
- customer/lead records;
- lifecycle stages;
- next actions;
- deduplication;
- activity timeline.

21. Customer Support Agent
- answer from approved knowledge;
- classify issues;
- propose resolution;
- escalate uncertain/high-risk cases.

22. Customer Success Agent
- onboarding;
- adoption;
- retention;
- feedback;
- renewal/upsell opportunities.

E6. OPERATIONS / FINANCE

23. Operations Agent
- SOPs;
- recurring workflows;
- operational task planning;
- bottleneck detection.

24. Finance Analysis Agent
- revenue/cost summaries;
- unit economics;
- margins;
- forecasts;
- pricing analysis;
- does NOT represent itself as a licensed accountant;
- does NOT execute financial transfers.

25. Analytics Agent
- KPI monitoring;
- anomaly detection;
- trend analysis;
- attribution where data permits;
- next-best-action recommendations.

E7. KNOWLEDGE / LEARNING

26. Knowledge Agent
- ingest approved sources;
- classify knowledge;
- retrieval quality;
- knowledge freshness;
- provenance.

27. Memory Curator Agent
- decide candidate durable memories;
- merge duplicates;
- expire stale operational memory;
- never store secrets as memory.

28. Optimization Agent
- compare plans to outcomes;
- identify improvements;
- propose experiments;
- recommend model/workflow optimizations.

E8. GOVERNANCE / RELIABILITY

29. QA / Reviewer Agent
- verify outputs against task requirements;
- factual/source checks where possible;
- code/build/test checks;
- block low-quality results.

30. Risk Agent
- evaluate proposed actions;
- assign risk class;
- enforce spend/data/action limits;
- trigger approvals.

31. Security Agent
- scan generated code/configuration;
- detect secrets;
- flag dangerous commands;
- check integration scope;
- never replace professional security testing.

32. Monitoring Agent
- detect worker failures;
- provider failures;
- stuck tasks;
- scheduler problems;
- deployment problems;
- integration expiry.

33. Audit Agent
- inspect whether actions match policies and approvals;
- identify inconsistent claims;
- produce audit findings;
- never alter audit history.

34. Legal/Compliance Assistant
- flag possible legal/compliance/trademark/privacy issues;
- cite evidence where possible;
- require human/professional review for consequential decisions;
- never act as final legal authority.

AGENT CONTRACT REQUIRED FOR EVERY AGENT
Each agent definition must include:
- agent_id
- version
- role
- purpose
- responsibilities
- non-responsibilities
- allowed task types
- allowed skills
- allowed tools
- forbidden tools/actions
- model policy
- data access scope
- risk level
- maximum autonomy
- input schema
- output schema
- evaluation criteria
- escalation criteria

======================================================================
SECTION F — SKILL SYSTEM
======================================================================

Agents do not own raw integrations.

Architecture:
Agent
 -> Skill
 -> Workflow/Tool
 -> Policy
 -> Provider Adapter
 -> External Service

Examples:

SEO Agent
 -> Keyword Research Skill
 -> Search tools
 -> Search provider

Marketing Agent
 -> Campaign Planning Skill
 -> Research + content + analytics tools

Website Agent
 -> Website Build Skill
 -> repository + filesystem + sandbox tools

Advertising Agent
 -> Meta Campaign Skill
 -> policy/approval
 -> Meta provider adapter

Each skill requires:
- skill_id
- version
- description
- compatible agents
- prerequisites
- input schema
- output schema
- tools
- workflow
- permissions
- risk class
- test fixtures
- evaluation rubric

======================================================================
SECTION G — MEMORY MODEL
======================================================================

Separate memory types.

1. Working Memory
Temporary context for the current execution.

2. Episodic Memory
Past task/action/outcome summaries.

3. Semantic Business Memory
Stable business facts and approved knowledge.

4. Decision Memory
Important decisions, rationale, approver, date.

5. Preference Memory
Founder-approved preferences.

6. Workflow Memory
Reusable successful operating procedures.

7. Evaluation Memory
Quality/outcome feedback used for future selection.

Memory requirements:
- provenance;
- timestamps;
- confidence/status;
- source links;
- revision history where important;
- ability to invalidate;
- no secrets;
- retrieval filters.

Agents must not treat model-generated assumptions as approved business facts.

======================================================================
SECTION H — GOVERNANCE MODEL
======================================================================

RISK CLASSES

R0 — Read-only/internal analysis
May run automatically.

R1 — Internal content creation
May run automatically subject to budget.

R2 — Reversible external action
Examples: draft publication, preview deployment.
Policy dependent.

R3 — External communication/publication
Human approval by default initially.

R4 — Financial spend, destructive action, privileged security/configuration
Explicit approval required.

R5 — Prohibited autonomous action
Examples include unsupported financial transfers or bypassing security controls.

Policy Engine checks:
- action;
- actor agent;
- tool;
- business;
- data classification;
- spend;
- frequency;
- target;
- approval requirements;
- time window;
- limits.

Global kill switch required for autonomous execution.

======================================================================
SECTION I — CORE DATA DOMAINS
======================================================================

Design only what each phase requires, but plan for these domains:

Identity / settings
businesses
business_profiles
business_goals
business_preferences
business_metrics

Strategy
research_projects
research_sources
competitors
customer_segments
business_plans
strategies
experiments

Agent system
agents
agent_versions
agent_runs
agent_messages
agent_tool_calls
agent_evaluations

Skills/workflows
skills
skill_versions
workflows
workflow_versions
workflow_runs
workflow_steps

Tasks
tasks
task_dependencies
task_events

Governance
policies
approvals
approval_events
risk_assessments
budgets

Knowledge
knowledge_sources
knowledge_items
documents
document_chunks
memories
decisions

Website
website_projects
website_versions
builds
deployments
domains

Marketing
campaigns
campaign_assets
content_items
content_calendar
seo_projects
keywords
social_posts
email_campaigns
ad_campaigns

CRM
leads
contacts
companies
opportunities
customer_interactions
support_cases

Operations
sops
operational_workflows
scheduled_jobs
scheduler_runs

Analytics
metric_definitions
metric_observations
analytics_events
insights

Finance
revenue_entries
expense_entries
budgets
financial_snapshots

Integrations
provider_configurations
integrations
integration_accounts
integration_events

System
events
notifications
audit_logs
usage_ledger
feature_flags

Do not create all tables in Phase 1.
Create migrations as domains are implemented.

======================================================================
SECTION J — DEVELOPMENT PHASES
======================================================================

PHASE 00 — FORENSIC BASELINE
Goal:
Understand the repository before implementation.

Actions:
- inspect entire repository tree;
- detect existing stack;
- inspect package files;
- inspect environment configuration;
- inspect DB/migrations;
- inspect tests;
- inspect CI;
- run current lint/tests/build;
- record existing failures;
- do not modify product behavior yet.

Create:
docs/FOUNDORA_MASTER_SPEC.md
docs/current-state.md
docs/implementation-status.md
docs/architecture.md
docs/open-questions.md
docs/decisions/

Acceptance:
- reproducible baseline;
- existing problems separated from new work;
- repository truth documented.

STOP.

PHASE 01 — FOUNDATION
Build:
- monorepo/application structure;
- frontend;
- API;
- worker;
- shared configuration;
- PostgreSQL;
- Redis;
- migrations;
- structured logging;
- health/readiness;
- Docker Compose;
- CI.

Acceptance:
- one documented local startup procedure;
- frontend loads;
- API health passes;
- DB migration passes;
- Redis reachable;
- worker starts;
- lint/typecheck/test/build pass.

STOP.

PHASE 02 — OWNER AUTHENTICATION & SECURITY BASE
Build:
- owner account;
- secure authentication;
- session lifecycle;
- protected routes;
- security headers;
- rate limiting baseline;
- secrets configuration;
- settings.

Do not build SaaS organizations/subscriptions.

Acceptance:
- unauthenticated access blocked;
- auth tests pass;
- no secret in repository/browser bundle.

STOP.

PHASE 03 — BUSINESS WORKSPACE
Foundora must support multiple businesses owned by the same founder even though it is not SaaS.

Build:
- create business;
- switch business;
- business profile;
- archive;
- business status;
- preferences;
- goals.

Acceptance:
- all operational data is scoped to selected business;
- business switching cannot mix data.

STOP.

PHASE 04 — BUSINESS ONBOARDING
Wizard:
- idea/existing business;
- name;
- industry;
- geography;
- problem;
- target audience;
- offer;
- goals;
- existing assets;
- constraints;
- budget;
- brand preferences;
- connected services.

AI may propose structured interpretations.
Founder approves final profile.

Acceptance:
- resumable;
- no AI assumption silently becomes fact.

STOP.

PHASE 05 — MODEL GATEWAY
Implement provider-independent AI gateway.

Adapters:
- OpenAI;
- Gemini;
- Claude/Anthropic when configured.

Features:
- provider validation;
- model registry;
- primary/fallback;
- task-specific routing;
- streaming;
- structured output;
- usage;
- latency;
- error logging;
- timeout;
- retry;
- token/cost budgets.

Acceptance:
- real configured provider works;
- missing key disables provider cleanly;
- fallback tested;
- usage persisted.

STOP.

PHASE 06 — COMPANY / BUSINESS BRAIN
Create unified context builder.

Context may include:
- profile;
- goals;
- approved strategy;
- products/services;
- brand;
- customers;
- decisions;
- knowledge;
- current tasks;
- KPIs;
- relevant memories.

Build Context Service with explicit token budgeting and source selection.

Acceptance:
- context is business-specific;
- provenance visible;
- stale/invalidated knowledge excluded.

STOP.

PHASE 07 — AGENT REGISTRY & RUNTIME
Implement:
- agent definitions;
- versioning;
- agent run lifecycle;
- structured inputs/outputs;
- model policy;
- permissions;
- errors;
- cancellation;
- usage linkage.

States:
queued
running
waiting_tool
waiting_approval
completed
failed
cancelled

Acceptance:
- one agent executes end-to-end;
- run can be inspected;
- failures persist honestly.

STOP.

PHASE 08 — SKILL REGISTRY
Implement:
- skills;
- versions;
- schemas;
- compatible agents;
- tool requirements;
- risk;
- evaluation rubric.

Create several harmless initial skills:
- summarize business context;
- generate structured plan;
- analyze provided data.

Acceptance:
- agent can invoke only assigned skills.

STOP.

PHASE 09 — TASK ENGINE
Build:
- goals;
- tasks;
- dependencies;
- priority;
- owner/agent;
- status;
- due dates;
- retries;
- events.

States:
draft
planned
queued
running
blocked
waiting_approval
completed
failed
cancelled

Acceptance:
- tasks persist;
- dependencies enforced;
- retry is safe.

STOP.

PHASE 10 — WORKFLOW ENGINE
Differentiate workflow from task.

Workflow supports:
- versioned definition;
- steps;
- dependencies;
- conditional branches;
- agent steps;
- tool steps;
- approval steps;
- wait steps;
- retries;
- compensation/rollback where possible.

Acceptance:
- execute a multi-step test workflow;
- resume after wait/approval;
- failure state is deterministic.

STOP.

PHASE 11 — POLICY, RISK & APPROVAL ENGINE
Implement:
- policies;
- risk classification;
- approvals;
- spend limits;
- tool permissions;
- autonomy levels;
- kill switch.

Acceptance:
- R3/R4 action cannot bypass approval;
- rejected approval cannot execute;
- audit trail complete.

STOP.

PHASE 12 — EVENT BUS
Create internal domain events.

Examples:
business.created
goal.created
task.completed
task.failed
approval.requested
website.deployed
lead.created
campaign.completed
metric.anomaly_detected

Requirements:
- event IDs;
- timestamps;
- idempotent consumers;
- retry/dead-letter strategy.

Acceptance:
- events trigger registered handlers exactly as designed.

STOP.

PHASE 13 — KNOWLEDGE INGESTION
Build:
- file upload;
- source registration;
- text extraction;
- metadata;
- chunking;
- embeddings;
- vector search;
- citations;
- invalidation.

Acceptance:
- uploaded document becomes retrievable;
- source citations preserved;
- malformed files fail cleanly.

STOP.

PHASE 14 — MEMORY SYSTEM
Implement memory types from Section G.

Memory Curator:
- proposes durable memory;
- founder/automatic policy determines acceptance;
- duplicates merged;
- stale memory can be invalidated.

Acceptance:
- assumptions cannot masquerade as facts;
- memory provenance visible.

STOP.

PHASE 15 — EXECUTIVE AGENTS
Implement:
- Founder/CEO Agent;
- Chief-of-Staff/Planning Agent.

CEO responsibilities:
- interpret founder objective;
- review business state;
- prioritize;
- delegate;
- request specialist work.

Acceptance:
- CEO produces traceable plan;
- does not directly execute forbidden tools.

STOP.

PHASE 16 — RESEARCH AGENTS
Implement:
- Market Research;
- Competitor Intelligence;
- Customer Research.

Build SearchProvider interface.

Research output requires:
- source;
- retrieval date;
- claim;
- confidence/limitations.

Acceptance:
- no invented competitor data;
- unsupported claims flagged.

STOP.

PHASE 17 — BUSINESS STRATEGY
Implement Business Strategist.

Artifacts:
- opportunity assessment;
- value proposition;
- business model;
- pricing hypotheses;
- positioning;
- GTM;
- launch roadmap;
- risks;
- assumptions requiring validation.

Acceptance:
- strategy tied to evidence and approved business facts.

STOP.

PHASE 18 — PRODUCT & OFFER SYSTEM
Build:
- products/services;
- packages;
- pricing;
- benefits;
- target segment;
- status;
- offer versions.

Implement Product & Offer Agent.

Acceptance:
- approved offers become structured business data.

STOP.

PHASE 19 — BRAND SYSTEM
Build:
- brand strategy;
- voice;
- messaging;
- tagline;
- visual direction;
- brand rules;
- asset references.

Implement Brand Agent.

Acceptance:
- content agents can retrieve approved brand rules.

STOP.

PHASE 20 — WEBSITE SPECIFICATION ENGINE
Before code generation create:
- site objective;
- sitemap;
- page specs;
- conversion goals;
- SEO requirements;
- content requirements;
- brand constraints;
- technical requirements.

Founder can review specification.

Acceptance:
- website generation never begins from a vague one-line prompt alone.

STOP.

PHASE 21 — WEBSITE/CODING AGENT
Implement:
- project generation;
- source edits;
- dependency management;
- tests;
- lint;
- accessibility checks;
- performance checks.

Coding agent must work through controlled repository/filesystem tools.

Acceptance:
- generated site builds successfully;
- no fake successful build.

STOP.

PHASE 22 — SANDBOX
Execute generated code only in isolation.

Controls:
- CPU;
- memory;
- timeout;
- process count;
- filesystem;
- network;
- no production credentials;
- cleanup.

Acceptance:
- resource limits verified;
- timeout verified;
- failed sandbox cleaned.

STOP.

PHASE 23 — WEBSITE QA AGENT
Review:
- build;
- broken links;
- responsive layout;
- accessibility;
- SEO;
- content completeness;
- obvious visual issues;
- forms;
- performance.

QA cannot approve a failing build.

Acceptance:
- QA report backed by executed checks.

STOP.

PHASE 24 — DEPLOYMENT
Create DeploymentProvider.

Lifecycle:
draft
building
preview
awaiting_approval
deploying
active
failed
rolled_back

Implement one real provider only when credentials are available.

Acceptance:
- real preview/deployment URL;
- status comes from provider;
- rollback tested where provider supports it.

STOP.

PHASE 25 — DOMAIN/DNS
Create DNSProvider.

Support:
- development/local host;
- Foundora-controlled subdomain when infrastructure exists;
- custom domain later.

Never claim DNS/SSL active before verification.

STOP.

PHASE 26 — CREATIVE ENGINE
Implement Creative Agent and ImageGenerationProvider abstraction.

Functions:
- creative brief;
- image prompt;
- asset generation;
- asset metadata;
- brand alignment;
- review.

Acceptance:
- provider absence degrades gracefully;
- generated assets are stored and traceable.

STOP.

PHASE 27 — SEO SYSTEM
Build:
- SEO project;
- keyword entities;
- intent;
- page mapping;
- technical audit;
- content opportunities;
- rankings data adapter when available.

Implement SEO Agent.

Acceptance:
- recommendations distinguish observed data from hypotheses.

STOP.

PHASE 28 — CONTENT SYSTEM
Build:
- content items;
- status;
- content calendar;
- channels;
- versions;
- approval;
- performance linkage.

Implement Content Agent.

Acceptance:
- published status requires real publication integration or explicit manual confirmation.

STOP.

PHASE 29 — MARKETING STRATEGY
Implement Marketing Strategist.

Build:
- campaign;
- objective;
- audience;
- funnel stage;
- channel;
- budget;
- assets;
- KPIs;
- start/end;
- status.

Acceptance:
- campaigns can exist as plans without pretending to be live.

STOP.

PHASE 30 — SOCIAL MEDIA
Create SocialProvider abstraction.

Implement Social Agent.

Initial behavior without provider:
- plan;
- create drafts;
- calendar;
- approval.

With provider:
- publish;
- fetch status;
- capture IDs/performance.

Acceptance:
- no fake posting.

STOP.

PHASE 31 — EMAIL MARKETING
Create EmailProvider.

Implement:
- email drafts;
- templates;
- campaigns;
- sequences;
- recipients/segments;
- send status;
- provider events.

Implement Email Marketing Agent.

Acceptance:
- external send requires approval initially;
- delivery/bounce status comes from provider.

STOP.

PHASE 32 — ADVERTISING
Create AdvertisingProvider.

Implement Advertising Agent.

Must enforce:
- daily spend limit;
- campaign spend limit;
- approval;
- account scope;
- budget changes;
- pause/kill control.

Without provider credentials:
planning only.

Acceptance:
- no monetary action without policy.

STOP.

PHASE 33 — CRM
Build:
- leads;
- contacts;
- companies;
- opportunities;
- lifecycle stages;
- activities;
- notes;
- next actions;
- deduplication.

Implement CRM Agent.

Acceptance:
- records are real structured data, not only chat memory.

STOP.

PHASE 34 — LEAD GENERATION
Implement Lead Generation Agent.

Rules:
- use permitted/public/connected sources;
- retain provenance;
- never invent email/phone/contact;
- respect provider/legal constraints;
- scoring must explain criteria.

Acceptance:
- every discovered lead has source provenance.

STOP.

PHASE 35 — SALES
Implement Sales Agent.

Functions:
- qualification;
- opportunity strategy;
- follow-up drafts;
- proposal support;
- pipeline next actions.

External sending requires approval/policy.

Acceptance:
- CRM timeline records actual actions.

STOP.

PHASE 36 — CUSTOMER SUPPORT
Build support cases.

Implement Support Agent:
- retrieve approved knowledge;
- answer with confidence;
- escalate uncertainty;
- track resolution.

Acceptance:
- unsupported answer is not presented as authoritative.

STOP.

PHASE 37 — CUSTOMER SUCCESS
Implement:
- onboarding tasks;
- customer goals;
- adoption indicators;
- feedback;
- retention risks;
- expansion opportunities.

Implement Customer Success Agent.

STOP.

PHASE 38 — OPERATIONS
Build:
- SOPs;
- recurring operational workflows;
- checklists;
- operational exceptions.

Implement Operations Agent.

Acceptance:
- SOP execution is task/workflow-backed.

STOP.

PHASE 39 — FINANCE ANALYSIS
Build optional/manual financial data ingestion first.

Track:
- revenue;
- expenses;
- categories;
- budgets;
- snapshots.

Implement Finance Analysis Agent.

Rules:
- clearly distinguish recorded data from forecasts;
- no banking transfers;
- no invented transactions.

STOP.

PHASE 40 — ANALYTICS
Create metrics framework.

Metric:
- definition;
- source;
- unit;
- aggregation;
- time range;
- freshness.

Implement Analytics Agent.

Dashboard must use real metrics only.

Acceptance:
- metric source can be traced.

STOP.

PHASE 41 — AUTONOMOUS OBSERVATION
Build observers for available signals:
- tasks;
- campaigns;
- website;
- leads;
- sales;
- costs;
- provider health;
- KPIs.

Observation creates candidate insights/events, not automatic actions.

STOP.

PHASE 42 — OPPORTUNITY / PROBLEM DETECTION
Implement rules + Analytics/Optimization reasoning.

Candidate:
- description;
- evidence;
- severity;
- opportunity value;
- confidence;
- recommended action.

Acceptance:
- every detected issue/opportunity has evidence.

STOP.

PHASE 43 — AUTONOMOUS PLANNING
CEO + Planning Agent:
- consume detected opportunities;
- prioritize;
- create goals/tasks/workflows;
- estimate cost/risk;
- submit high-risk plans for approval.

Acceptance:
- autonomous plan is inspectable before execution.

STOP.

PHASE 44 — SCHEDULER
Build durable scheduler.

Scheduler only emits/enqueues work.
It must not contain business logic.

Features:
- one-time;
- daily;
- weekly;
- monthly;
- cron-like internal schedule;
- pause;
- resume;
- missed-run policy;
- idempotency.

Acceptance:
- worker/API restart does not orphan schedules.

STOP.

PHASE 45 — AUTONOMOUS EXECUTION LOOP
Connect:
Observe
-> Detect
-> Prioritize
-> Plan
-> Policy
-> Approval
-> Execute
-> QA
-> Measure
-> Learn

Begin with autonomy disabled by default.

Modes:
OFF
RECOMMEND
ASSISTED
AUTONOMOUS_LOW_RISK

Never introduce unrestricted autonomous mode.

Acceptance:
- kill switch works;
- risk controls cannot be bypassed;
- full run trace exists.

STOP.

PHASE 46 — OUTCOME MEASUREMENT
Every significant autonomous action should define expected outcome.

Track:
- baseline;
- action;
- expected metric;
- observation window;
- actual outcome;
- result;
- confidence.

STOP.

PHASE 47 — AGENT EVALUATION
Implement QA/Reviewer + evaluation framework.

Evaluate:
- correctness;
- completeness;
- evidence;
- policy compliance;
- tool correctness;
- task outcome.

Do not allow agents to rewrite their own system prompts automatically.

Agent improvement produces a proposed new version requiring review.

STOP.

PHASE 48 — OPTIMIZATION AGENT
Analyze:
- successful workflows;
- failures;
- cost;
- latency;
- model quality;
- business outcomes.

Recommend:
- workflow changes;
- model routing;
- skill changes;
- business experiments.

STOP.

PHASE 49 — MONITORING AGENT
Monitor:
- API;
- DB;
- Redis;
- workers;
- scheduler;
- queues;
- integrations;
- AI providers;
- deployments;
- stuck runs.

Monitoring Agent creates alerts/tasks.
It does not hide errors.

STOP.

PHASE 50 — SECURITY AGENT + HARDENING
Security Agent assists with:
- dependency findings;
- secret detection;
- dangerous generated code;
- permission anomalies;
- integration scopes.

Also perform conventional security testing:
- authorization;
- input validation;
- upload security;
- rate limits;
- SSRF;
- injection;
- sandbox isolation;
- webhook verification;
- prompt injection;
- secret scanning.

STOP.

PHASE 51 — AUDIT AGENT
Implement immutable audit trail.

Audit Agent checks:
- claimed vs actual execution;
- approval compliance;
- tool scope;
- budget compliance;
- suspicious repeated failures.

Audit Agent cannot modify audit history.

STOP.

PHASE 52 — LEGAL/COMPLIANCE ASSISTANT
Capabilities:
- checklist;
- policy/document review support;
- trademark/business-name research workflow;
- privacy/compliance flags;
- evidence gathering.

Must display professional-review requirement for consequential matters.

STOP.

PHASE 53 — NOTIFICATIONS
Channels:
- in-app first;
- email when provider configured;
- messaging later.

Events:
- approval required;
- task failed;
- deployment failed;
- integration expired;
- budget threshold;
- autonomous opportunity;
- critical monitoring alert.

STOP.

PHASE 54 — OWNER CONTROL CENTER
Build one real operational console.

Sections:
- business health;
- goals;
- tasks;
- agents;
- workflows;
- approvals;
- autonomous runs;
- website;
- marketing;
- CRM;
- customers;
- analytics;
- finance;
- integrations;
- AI usage;
- provider health;
- alerts;
- audit.

No fabricated counters.

STOP.

PHASE 55 — AI & INFRASTRUCTURE COST LEDGER
Track:
- provider;
- model;
- agent;
- task;
- workflow;
- tokens;
- estimated/actual provider cost;
- storage;
- deployment cost where available;
- email/ad spend where available.

Goal:
know cost per business/action/outcome.

STOP.

PHASE 56 — OBSERVABILITY
Implement:
- structured logs;
- request IDs;
- task IDs;
- agent run IDs;
- workflow run IDs;
- tool call IDs;
- traces;
- metrics;
- error tracking.

One action should be traceable:
UI -> API -> Task -> Agent -> Skill -> Tool -> Provider -> Result.

STOP.

PHASE 57 — BACKUP & RECOVERY
Create:
- DB backup procedure;
- object storage recovery procedure;
- config recovery;
- migration rollback strategy;
- restore test;
- runbook.

A backup is not considered valid until restore is tested.

STOP.

PHASE 58 — PERFORMANCE & COST OPTIMIZATION
Measure first.

Optimize:
- DB indexes;
- N+1 queries;
- caching;
- queue concurrency;
- context size;
- model selection;
- duplicate AI calls;
- embeddings;
- generated assets;
- build concurrency.

STOP.

PHASE 59 — PRODUCTION CONFIGURATION
Only after product passes prior phases.

Map:
Frontend -> chosen frontend host
API -> chosen container/server host
PostgreSQL -> managed PostgreSQL
Redis -> managed Redis
Files -> object storage
DNS/CDN -> provider
AI -> configured provider APIs
Email -> configured provider
Deployment -> configured provider
Monitoring -> monitoring provider

Create staging before production.

STOP.

PHASE 60 — FULL SYSTEM REGRESSION
Run complete scenario:

1. create business;
2. onboard business;
3. research market;
4. analyze competitors;
5. define customer;
6. build strategy;
7. define offer;
8. create brand;
9. specify website;
10. generate website;
11. sandbox build;
12. QA;
13. preview/deploy;
14. build SEO plan;
15. build marketing campaign;
16. create content;
17. create lead;
18. progress CRM;
19. run operations task;
20. ingest financial data;
21. view analytics;
22. detect opportunity;
23. autonomous planner creates work;
24. approval;
25. execution;
26. outcome measurement;
27. memory/evaluation;
28. audit.

Any broken link in this chain must be fixed before declaring complete.

STOP.

PHASE 61 — FIRST REAL BUSINESS LAUNCH
Use Foundora on one real founder-owned business.

Do not use demo assumptions.

Record:
- time to research;
- time to strategy;
- time to website;
- number of human approvals;
- agent failures;
- cost;
- launch blockers;
- quality problems;
- manual interventions.

Fix product gaps based on evidence.

STOP.

PHASE 62 — PRODUCT COMPLETION AUDIT
Perform forensic comparison:
MASTER SPEC
vs
REPOSITORY
vs
DATABASE
vs
ROUTES
vs
UI
vs
WORKERS
vs
SCHEDULER
vs
INTEGRATIONS
vs
TESTS
vs
RUNTIME

For every requirement classify:
IMPLEMENTED
PARTIAL
NOT IMPLEMENTED
BLOCKED
DEFERRED BY DESIGN

Never use "complete" for PARTIAL.

Create:
docs/final-product-audit.md

======================================================================
SECTION K — REQUIRED USER INTERFACE
======================================================================

Primary navigation should eventually include:

Home / Command Center
Businesses
Goals
AI Team
Tasks
Workflows
Approvals
Research
Strategy
Brand
Products & Offers
Website
SEO
Marketing
Content
Social
Email
Advertising
Leads
CRM / Sales
Customers
Support
Operations
Finance
Analytics
Knowledge
Memory
Integrations
Automation
Activity / Audit
Settings

Do not expose empty dead sections before their phase is implemented.
Use feature flags or hide them.

======================================================================
SECTION L — COMMAND CENTER
======================================================================

The home screen must answer:

1. What is happening?
2. What needs my approval?
3. What is failing?
4. What opportunity did Foundora discover?
5. What is Foundora working on?
6. What changed?
7. What are my business KPIs?
8. What should I do next?
9. What did AI/infrastructure cost?
10. Is autonomy currently enabled?

Every displayed value must map to real state.

======================================================================
SECTION M — AUTONOMY SAFETY
======================================================================

Default:
AUTONOMY = OFF or RECOMMEND.

Founder explicitly enables:
ASSISTED
or
AUTONOMOUS_LOW_RISK.

Always require approval initially for:
- sending external messages at scale;
- public publishing where configured;
- advertising spend;
- payment/billing changes;
- destructive operations;
- credential changes;
- production deployment if policy says so;
- deletion of customer/business data.

Provide:
- global kill switch;
- per-agent disable;
- per-skill disable;
- per-provider disable;
- per-workflow pause;
- spend caps;
- task caps;
- schedule pause.

======================================================================
SECTION N — TESTING STRATEGY
======================================================================

Unit tests:
- business logic;
- policy;
- routing;
- parsers;
- risk;
- schemas.

Integration tests:
- DB;
- Redis;
- task engine;
- workflow;
- agent runtime;
- tool runtime.

Contract tests:
- provider adapters.

End-to-end:
- core founder journeys.

Security:
- authorization;
- secrets;
- sandbox;
- uploads;
- webhooks;
- prompt injection.

Reliability:
- worker crash;
- provider timeout;
- rate limit;
- scheduler restart;
- duplicate webhook;
- retry;
- partial workflow failure.

AI evaluation:
- deterministic fixtures where possible;
- rubric evaluation;
- source grounding;
- schema adherence;
- hallucination checks.

======================================================================
SECTION O — CODING AGENT PHASE START PROTOCOL
======================================================================

At the beginning of EVERY phase, the coding agent must output:

PHASE:
OBJECTIVE:
CURRENT REPOSITORY EVIDENCE:
DEPENDENCIES ALREADY IMPLEMENTED:
FILES/MODULES EXPECTED TO CHANGE:
DATABASE IMPACT:
API IMPACT:
UI IMPACT:
SECURITY IMPACT:
TEST PLAN:
OUT-OF-SCOPE FOR THIS PHASE:

Then implement.

Do not merely output a plan and claim completion.

======================================================================
SECTION P — CODING AGENT PHASE COMPLETION PROTOCOL
======================================================================

At phase end output:

PHASE:
STATUS: COMPLETE / PARTIAL / BLOCKED

IMPLEMENTED:
- exact items

NOT IMPLEMENTED:
- exact items

FILES CHANGED:
- exact paths

DATABASE:
- migrations/tables/indexes

API:
- routes/contracts

UI:
- pages/components

AGENTS/SKILLS/WORKFLOWS:
- exact changes

PROVIDERS:
- exact changes

SECURITY:
- controls added

TESTS EXECUTED:
- command
- result

BUILD/LINT/TYPECHECK:
- command
- result

RUNTIME/SMOKE TEST:
- exact verification

KNOWN LIMITATIONS:
- exact limitations

OPEN QUESTIONS:
- questions requiring founder decision

REGRESSION CHECK:
- existing functionality verified

NEXT PHASE:
- name only

Then STOP.

======================================================================
SECTION Q — STRICT COMPLETION LANGUAGE
======================================================================

Allowed:
"Implemented and verified"
"Implemented but provider credentials are not configured"
"UI complete; external integration intentionally disabled"
"Partial"
"Blocked"

Forbidden unless verified:
"Fully production-ready"
"Everything works"
"Deployment successful"
"Email sent"
"Campaign live"
"Agent autonomous"
"Integration connected"

======================================================================
SECTION R — EXTERNAL API KEY BEHAVIOR
======================================================================

If founder supplies OpenAI/Gemini/Claude API key:
- validate it through provider adapter;
- encrypt/store securely as appropriate;
- expose provider status;
- list usable models where API permits;
- allow routing policy;
- record usage.

If key is absent:
- provider is DISABLED;
- application remains usable where possible;
- no fake AI output.

If an email/social/ad/deployment/payment/search API is supplied:
- the relevant adapter must already exist or be implemented in its phase;
- validate credentials;
- expose capability status;
- only then enable corresponding tools.

An API key alone does not create a capability.
Capability = Adapter + Credentials + Permissions + Tool + Policy + Tests.

======================================================================
SECTION S — FUTURE SAAS CONVERSION BOUNDARY
======================================================================

DO NOT IMPLEMENT NOW, but preserve extension paths for:
- organizations;
- tenants;
- subscriptions;
- per-tenant billing;
- public signup;
- tenant-specific secrets;
- tenant quotas;
- team RBAC;
- enterprise SSO;
- multi-region;
- fleet-scale hosting.

Core modules that MUST remain reusable later:
- agent runtime;
- skills;
- workflows;
- tasks;
- policies;
- approvals;
- model gateway;
- provider adapters;
- knowledge;
- memory;
- business domains;
- website factory;
- analytics;
- autonomous loop.

======================================================================
SECTION T — FINAL DEFINITION OF PRODUCT COMPLETION
======================================================================

Foundora V1 is considered complete only when a real founder can:

- create a real business workspace;
- provide a real business idea;
- obtain source-backed research;
- obtain competitor/customer analysis;
- create an approved business strategy;
- define products/services/offers;
- establish brand rules;
- generate and successfully build a website;
- preview/deploy it when provider credentials are configured;
- build SEO and marketing plans;
- create real structured CRM/operational data;
- use configured providers without code changes to core business logic;
- run specialized agents through the shared runtime;
- run multi-agent workflows;
- control risky actions through approvals;
- schedule recurring work;
- enable low-risk autonomous operation;
- see what every agent/task/tool actually did;
- measure outcomes;
- maintain business knowledge/memory;
- inspect AI/provider costs;
- stop autonomous execution immediately;
- recover from common provider/worker failures;
- complete a full regression test;
- use Foundora to launch at least one real business.

The final product must not depend on mock data for its normal operating path.

======================================================================
FINAL COMMAND TO THE CODING AGENT
======================================================================

You are building Foundora, not demonstrating Foundora.

Do not optimize for the appearance of progress.
Optimize for verified working capability.

Read this specification before every phase.
Read the repository before every change.
Use actual evidence.
Never fabricate success.
Never bypass tests because implementation is large.
Never silently weaken requirements.
Never jump ahead.
Never expose secrets.
Never allow agents to bypass the policy/approval layer.
Never treat model-generated assumptions as business facts.
Never mark a phase complete when acceptance criteria fail.

Start with PHASE 00 only.
When PHASE 00 is verified, produce the required completion report and STOP.
Wait for explicit authorization before PHASE 01.

END OF FOUNDORA MASTER BUILD SPECIFICATION
