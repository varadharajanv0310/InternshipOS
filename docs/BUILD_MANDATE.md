Use the completed Phase 0 research as the technical reference for InternshipOS, but **do not execute its roadmap literally**. The research is finished. Do not start another research phase, do not create another giant audit/checklist, and do not spend time proving things for weeks before continuing. This is a personal system for one college student, not an enterprise product.

The goal now is simple:

> **Build InternshipOS as a polished, complete personal internship intelligence system that maximizes useful internship coverage while keeping recurring cost extremely low.**

The research already established the important technical foundations: React/Vite/TypeScript, FastAPI/Python, PostgreSQL, direct ATS extraction, Postgres search, Python ingestion, JobSpy where useful, evidence-aware matching, Gmail/Calendar integration, resume intelligence, analytics and browser-assisted applications. Keep those decisions unless implementation reveals a concrete technical reason to change them. :chatgpt-content-reference{index="0"}

## Revised build philosophy

Do **not** follow the original “Phase 1 → wait 7–14 days → manually validate hundreds of records → Phase 2” process. The original roadmap proposed a 7–14 day collection gate before continuing. That level of ceremony is unnecessary here. :chatgpt-content-reference{index="1"}

Build continuously.

As soon as ingestion works, keep it running while the rest of the application is built. Testing and validation happen alongside development, not as week-long blockers.

Also, do not intentionally build a rough MVP that will supposedly become good later. The first implementation should already be the real product: strong architecture, polished frontend, responsive layouts, sensible animations, robust ingestion, proper scoring, useful analytics and clean interactions.

Where the Phase 0 logical data model is detailed, it is acceptable to implement it properly rather than deliberately making a throwaway schema. Preserve the important distinctions between companies, sources, source observations, canonical internships, applications, events, resume versions and evidence. Do not add complexity purely for enterprise scale, tenancy or hypothetical future users.

## Coverage is the primary product objective

InternshipOS must **not** become a scraper for four websites.

If all it does is search LinkedIn, Indeed, Internshala and Unstop, there is little reason to build it because the user can already check those manually.

The system should aim to capture as much of the relevant public internship market as practical.

Start with approximately **200 known, legitimate companies**, but treat those as a trusted seed and priority set—not the limits of the search universe.

As opportunities are found elsewhere:

1. detect the company,
2. investigate whether it is legitimate,
3. identify its official website/careers presence,
4. resolve its ATS or job source when possible,
5. add it to the monitored company registry,
6. retain the discovery source as provenance.

The registry should therefore grow naturally from hundreds toward thousands over time.

Smaller or lesser-known companies are acceptable. A company does not need to be famous. What matters is whether the company and internship appear genuine and worthwhile.

## Roles to capture

Primary search categories should include:

- Software Engineering / SDE
- Full Stack Development
- Frontend
- Backend
- Mobile development
- Data Science
- Data Engineering
- Analytics / technical analytics
- Analytics Engineering
- Machine Learning
- AI / applied AI
- NLP / computer vision where relevant
- Cloud
- DevOps
- SRE
- Cybersecurity / security engineering
- Database/platform/devtools roles
- sensible adjacent CSE/technical roles

The Phase 0 classifier already supports SWE, Data, AI/ML and adjacent technical categories and separates real job substance from misleading titles. :chatgpt-content-reference{index="2"}

Also classify **graduate/fresher roles and apprenticeships separately** when this can be done reliably. They do not need to contaminate the internship feed, but they can still be useful opportunities.

Unpaid internships should not automatically disappear. They should remain discoverable but receive lower Apply-Worthiness where appropriate.

## Source strategy

Use every worthwhile source that improves coverage.

The source architecture should include several layers.

### Direct company and ATS sources

These are preferred whenever available because they provide strong identity and application links.

Support the high-value ATS families identified during Phase 0, including:

- Greenhouse
- Lever
- Ashby
- Workday
- SmartRecruiters
- Oracle Recruiting
- Eightfold
- iCIMS
- Workable
- BambooHR
- Taleo where practical
- SuccessFactors
- Recruitee
- Personio
- Teamtailor
- Zoho Recruit
- UKG
- Breezy
- Pinpoint
- Phenom
- JazzHR
- Paylocity
- other ATS families from the researched matrix when they contribute useful jobs

Do **not** implement all 23 merely to satisfy the research matrix. Implement them based on actual coverage contribution. The matrix is a reference, not a launch checklist. :chatgpt-content-reference{index="3"}

Also support important custom career systems such as major technology, finance and enterprise employers whenever the monitored company set requires them.

### Job boards and internship platforms

These are important because they discover companies the direct registry may never know about.

Include, when technically practical:

- LinkedIn
- Indeed
- Naukri
- Internshala
- Unstop
- Wellfound
- Cutshort
- Instahyre
- Foundit
- Freshers-oriented/off-campus sources where worthwhile
- credible internship/fresher announcement websites
- maintained internship repositories/lists
- other India-focused technical hiring platforms found during implementation

The Phase 0 research explicitly found working paths for several of these while also identifying failures such as Naukri CAPTCHA. Those failures should be visible instead of being misinterpreted as “zero internships.” :chatgpt-content-reference{index="4"}

For Naukri or any other difficult platform, do not allow one difficult scraper to stall the rest of the project. Use the best legitimate path available: public data, alerts, imports, extension capture or later paid/licensed access if the source proves uniquely valuable.

### Registry/aggregation sources

Use JobSeek, Open Jobs and Freehire as seeds and supplemental discovery where useful.

Do not adopt Freehire wholesale simply because it already contains many sources. Extract useful techniques/data while keeping InternshipOS's own canonical model and relevance filters.

### Browser/manual capture fallback

Any internship page the user encounters should eventually be capturable into InternshipOS even if that source has no dedicated adapter.

The browser extension should therefore support a **Save to InternshipOS** flow in addition to application automation.

## Canonicalization and deduplication

Keep the conservative Phase 0 approach here. This is one of the parts that should **not** be simplified away.

Prefer:

1. source-scoped ATS/job ID,
2. employer-scoped requisition ID,
3. canonical employer/application URL,
4. strong corroborating evidence,
5. fuzzy similarity only as secondary evidence.

Never assume two jobs are identical solely because company, title and location look similar.

Different trusted requisition IDs should remain separate.

Probable duplicates can be visually grouped rather than destructively merged.

Every merge must be reversible.

If an internship disappears, do not immediately mark it closed. Closure should require a healthy complete scan or authoritative evidence. CAPTCHA, HTTP errors, parser failures or partial pagination mean **source failure**, not job closure. Phase 0 correctly identified false merges and false closures as high-impact failure modes. :chatgpt-content-reference{index="5"}

## Polling and freshness

Optimize for cost and coverage, not minute-level freshness.

A college internship appearing a few hours later generally does not matter.

Suggested initial cadence:

- high-priority company ATSs: every **6–12 hours**
- normal monitored companies: every **12–24 hours**
- long-tail company sources: daily
- major aggregators/platform searches: once or twice daily depending on cost and reliability
- fragile/expensive sources: daily or on-demand
- active saved jobs: periodically refresh the full JD/deadline to detect material changes

These should remain configurable.

Browser automation should only be used when structured HTTP/API/HTML approaches are insufficient.

## Deployment and cost philosophy

The system should be designed to operate for **free or very close to free**.

Do not assume a VPS is required merely because the original research proposed one.

Prefer free/low-cost infrastructure first if it preserves the same source coverage:

- Vercel for the frontend and ordinary API endpoints if suitable
- a free PostgreSQL option such as Neon/Supabase-compatible Postgres where practical
- scheduled collection through free scheduling/CI infrastructure where it provides enough runtime
- no Redis
- no dedicated vector database
- no Elasticsearch/OpenSearch
- no analytics warehouse
- no paid browser farm
- no proxy network
- no Apify dependency
- no paid scraping platform unless real measurements later prove it adds valuable unique internships

If persistent workers, runtime limits or scraper behavior eventually make this inconvenient, add a small DigitalOcean VPS. The VPS is a fallback/upgrade, not a mandatory starting expense.

If a VPS is used, the architecture can remain simple:

- Docker Compose
- FastAPI
- PostgreSQL
- workers/scheduler
- static services if needed
- encrypted secrets
- TLS
- off-machine backup

Choose a region reasonably close to India if latency/source behavior warrants it.

## AI budget and role

AI spending must remain within approximately **$2–3 per month**.

InternshipOS must continue functioning if the AI budget reaches zero.

AI is **not** the acquisition engine.

Do not spend model calls on deterministic work such as:

- fetching ATS records
- parsing IDs
- reading structured location fields
- straightforward internship-title classification
- exact deduplication
- canonical URL normalization
- ordinary database filtering
- analytics queries
- source health
- application-state storage

Use the Phase 0 hierarchy:

**structured ATS fields → JSON-LD → labelled DOM/text parsing → regex/rules → model fallback.** :chatgpt-content-reference{index="6"}

Use a cheap model for difficult language/ambiguity and reserve stronger reasoning for valuable cases.

AI is justified for:

- ambiguous internship classification
- vague technical role classification
- complicated eligibility clauses
- JD summarization where deterministic extraction is insufficient
- nuanced missing-skills analysis
- fit explanations
- Apply-Worthiness explanations
- suspicious/scam language interpretation
- resume tailoring
- job-specific project selection
- unusual application questions
- difficult recruiting emails

Use the cheapest model that meets accuracy requirements.

A reasonable initial architecture is Luna-class cheap inference for automated ambiguity and Sol-class reasoning only when needed. However, price matters heavily. Keep a provider abstraction so cheaper Gemini/Claude/local models can be benchmarked and substituted if they offer better cost/intelligence.

Strong-model operations should generally be either:

- restricted to excellent/high-value opportunities, or
- explicitly user-triggered, such as **Deep Analyze**, **Tailor Resume**, or **Draft Answer**.

Implement a hard monthly AI budget. When the limit is reached, optional model jobs pause; scraping, deterministic scoring, tracking and the UI continue normally.

## Eligibility, Fit and Apply-Worthiness

Do not overcomplicate eligibility in the main UI.

Internally preserve enough evidence and uncertainty to reason safely, but user-facing output can be simpler:

- Eligible
- Unclear
- Ineligible

with details available when needed.

Fit should remain a **0–100 score**, using the initial Phase 0 weighting unless better evidence emerges:

- role/career alignment
- required skills
- preferred skills
- projects/experience/research
- education
- location/work-mode/duration

The research intentionally separates these factors and prevents missing information from being treated as a mismatch. :chatgpt-content-reference{index="7"}

Instead of showing awkward ranges such as `58–93` as the main interface, prefer:

> **Fit 86 · Medium confidence**

Then expose unknowns and evidence in the expanded breakdown.

Keep **Apply-Worthiness** separate from Fit.

Fit asks:

> How well does this opportunity match the user?

Apply-Worthiness asks:

> Is this opportunity worth spending application effort on?

Worth may include:

- Fit
- role quality
- learning potential
- compensation
- location
- engineering/company relevance
- effort required
- internship quality
- potential conversion/PPO evidence
- urgency

Company reputation/quality can influence Worth, but it should not falsely increase technical Fit.

Urgency should remain separately visible so an expiring mediocre internship does not magically become an excellent opportunity.

## Company legitimacy and fraud

Because broad discovery will encounter fake or low-quality employers, company verification is important.

Do not make an LLM the fraud judge.

Use evidence such as:

- official domain existence
- official careers association
- ATS ownership/redirect evidence
- company history and public presence
- suspicious lookalike domains
- application fees/deposits
- credential/OTP/bank requests
- questionable redirects
- recruiter identity
- known scam indicators
- suspicious language
- mismatched role/company information

User-facing trust should emphasize understandable states such as:

- Verified
- No obvious concern
- Needs review
- High risk

Avoid pretending an internal score such as `63/100` is a scientifically calibrated fraud probability.

Unknown is not the same as safe.

## Compensation

Always capture stated stipend/pay where present.

Clearly distinguish:

- employer-stated compensation
- prior observed compensation
- user-reported compensation
- estimated compensation
- unknown compensation

Do not let AI invent compensation.

Sophisticated salary/stipend estimation is lower priority. Build it after stated compensation and historical observations work well.

Offer comparison should compare actual dimensions rather than declaring one simplistic winner.

## User profile and privacy

The system is single-user.

Allow enough non-sensitive profile information on the backend to make always-on matching useful:

- education
- branch
- CGPA
- graduation year
- role preferences
- skills
- project references
- availability
- location preferences
- internship-duration preferences

Keep highly sensitive data local when possible:

- browser cookies/sessions
- personal address
- reusable sensitive application answers
- private identity documents
- applicant authentication sessions

Do not place browser cookies on the server.

## Resume Vault and GitHub project intelligence

Build a structured Resume Vault.

Support multiple variants such as:

- SWE/FSD
- Data
- ML/AI
- other specialized variants where justified

Do not treat PDFs as the source of truth.

Maintain structured facts, experience bullets, projects, skills and evidence, then render deterministic resume versions.

Connect the user's GitHub account through the GitHub API/OAuth where appropriate.

InternshipOS should maintain a factual project inventory containing:

- repository
- project name
- technologies
- description
- actual features
- measurable factual achievements
- role relevance
- project category
- approved resume bullets

When a job is analyzed, it should be able to select and swap in the most relevant factual projects for that role.

For example, a Data Engineering internship may use different projects than an AI/ML internship.

AI may reorder/rephrase approved facts, but must never invent achievements, metrics, technologies or experience.

Track the exact resume version submitted to each company.

Resume tailoring should generally be on-demand rather than generated for every discovered posting.

Cover letters should be generated only when required or explicitly requested.

## Gmail integration

Do not depend on the ChatGPT Gmail connector as InternshipOS's runtime backend. InternshipOS itself should use Google's Gmail API/OAuth.

The ChatGPT connector can still be useful during development/testing, but the finished application needs its own integration.

Polling every 5–15 minutes is unnecessary.

Start around **30–60 minutes**, possibly slower overnight.

Use read-only Gmail initially.

Detect:

- application confirmation
- OA/assessment invitation
- recruiter contact
- interview invitation
- rejection
- offer
- additional-document request
- reschedule/cancellation

When the evidence clearly identifies one application, automatically update the application state and create the appropriate task/event.

Ambiguous emails should go to review.

All automated state changes must be reversible.

In the future, recruiter-response drafting/sending may be added with explicit user approval.

## Calendar

Integrate Google Calendar.

Use a dedicated InternshipOS-owned calendar rather than cluttering or taking control of the user's main calendar.

Automatically add exact:

- interview times
- confirmed calls
- important OA deadlines
- offer deadlines where useful

For uncertain dates/times, create a task/review item rather than inventing an exact event.

Important deadlines can exist both as tasks and calendar entries.

## Applications and state model

Core application stages should remain easy to understand:

**Ready → Applied → OA → Interview → Offer / Rejected**

Keep preparation separate from submission.

Support multiple applications to the same company.

A job closing after submission must not automatically mean rejection.

For no-response/ghosting, use elapsed-time indicators. If desired, the UI may eventually categorize a very old inactive application as effectively inactive/rejected for workflow cleanliness, but preserve the historical truth that no explicit rejection was received.

Manual corrections should preserve event history rather than deleting previous state.

## Application preparation and browser extension

Ship value before the full extension is finished.

The first application helper can provide a **prepared application pack**:

- recommended resume
- resume download
- job link
- company information
- reusable factual answers
- custom-answer drafts
- requirements checklist
- unresolved questions
- easy copy actions

Then build the attended Manifest V3 browser extension.

The extension should:

- detect supported application forms
- connect to InternshipOS
- select the correct resume
- fill known factual fields
- handle reusable questions
- upload the correct resume
- mark uncertain fields
- allow copying prepared answers
- survive multi-page flows when supported
- capture/save unknown job pages into InternshipOS

### Auto-apply requirement

Auto-apply is a desired end-state capability and should **not be silently excluded** because the original research was conservative.

Design the architecture so supported applications can eventually be submitted automatically when the user has explicitly enabled auto-apply for that category/source and all required data is known.

However:

- never invent legal/authorization/demographic answers
- never fabricate resume facts
- stop on ambiguous mandatory questions
- stop when required credentials/profile data are missing
- preserve an application receipt/evidence trail
- do not consider a form applied merely because fields were filled
- CAPTCHA should hand control back to the user rather than making CAPTCHA circumvention a core dependency

The aim is reliable auto-application where forms are well understood, not blindly clicking Submit across arbitrary sites.

## Product pages

Keep the product structure researched in Phase 0: :chatgpt-content-reference{index="8"}

### Home

This should be a **large, rich command-center dashboard**, not a tiny minimalist landing page.

Include useful information such as:

- strongest new opportunities
- new internships since last visit
- urgent applications
- OA/interview deadlines
- recent recruiter activity
- application funnel
- source coverage
- response statistics
- recent company discoveries
- source/system health
- AI spend
- relevant trends

Do not let the dashboard become visually chaotic, but analytics are a central requirement.

### Opportunities

Powerful table/feed with filters for:

- role
- company
- location
- remote status
- eligibility
- fit
- worth
- stipend
- freshness
- source
- risk
- application state

Support saved views.

### Opportunity Detail

Show:

- summary
- Fit
- Apply-Worthiness
- eligibility
- missing skills
- requirements
- location/work mode
- compensation
- company
- legitimacy/risk
- recommended resume
- application readiness
- source provenance
- original full JD
- history/changes

### Applications

Support both:

- table
- Kanban

Keep a timeline and exact resume used.

### Companies

Company verification, ATS sources, jobs, application history, offices, legitimacy evidence and monitoring controls.

Do **not** turn this into a recruiter/networking CRM.

### Tasks

Application/OA/interview/deadline actions only.

### Calendar

Agenda/week views for application-related events.

### Analytics

This is a **major feature**, not a small chart page.

### Resumes

Master profile, role variants, exact versions, tailoring history and GitHub project selection.

### Activity

Show important automated/user/system changes with correction controls.

### Settings

Profile, locations, roles, budget, source cadence, integrations, privacy, notifications and backups.

Do **not** add a generic chatbot.

## Analytics philosophy

Phase 0 defines 93 metric IDs. Do not feel compelled to build 93 visualizations immediately, but instrument the underlying data properly from the beginning. :chatgpt-content-reference{index="9"}

Analytics should eventually include:

- raw discoveries
- unique internships
- duplicates
- source contribution
- exclusive source contribution
- source failures
- company coverage
- ATS coverage
- geographic distribution
- role distribution
- skill demand
- stipend distributions
- Fit distribution
- Worth distribution
- applications/week
- applications/month
- qualified→applied rate
- OA rate
- interview rate
- offer rate
- response rate
- rejection rate
- response timing
- resume usage/outcomes
- applications by company/source/location/role
- backlog
- preparation effort
- source freshness
- extraction completeness
- Gmail matching accuracy
- autofill success
- cost usage
- AI spend
- backup health
- system health

Use correct denominators and canonical internship IDs so overlapping sources do not inflate statistics.

Analytics should be descriptive. Do not claim one resume “caused” interviews because the sample is tiny.

## Notifications

Build:

- morning digest
- strong/new opportunity alerts
- OA alerts
- interview alerts
- important recruiter-message alerts
- upcoming deadlines
- persistent source/integration failures where they actually matter

Do not spam the user for every routine fetch.

Additional notification channels can be added later.

## UI and design

Use the researched Apple/Linear-inspired direction, but execute it properly from the first pass. :chatgpt-content-reference{index="10"}

The product should feel polished, modern and intentionally designed—not like an admin dashboard generated by a backend engineer.

Use:

- strong typography
- precise spacing
- restrained surfaces
- excellent information hierarchy
- high-quality tables
- responsive layouts
- proper empty/loading/error states
- subtle motion
- light and dark mode
- persistent desktop sidebar
- split/detail panes where useful
- keyboard shortcuts/actions
- mobile-friendly triage views

Glass/material effects should be selective rather than placed behind every table/card.

There is **no separate future “make the UI good” phase**. Build the real visual system while building the product.

## Explicitly avoid unnecessary scope

Do not build:

- SaaS tenancy
- team accounts
- billing/subscriptions
- public profiles
- networking/referral CRM
- generic notes
- generic file manager
- generic calendar replacement
- interview-practice system
- learning platform
- generic chatbot
- Kubernetes
- Kafka
- Redis unless later proven necessary
- separate vector database
- separate search cluster
- analytics warehouse
- expensive proxy infrastructure by default
- general autonomous-agent framework

The system should remain focused on finding internships, understanding them, helping the user apply, tracking what happens, and analyzing the process.

## Execution

Begin implementation immediately.

Do not write another large research package.

Do not create another multi-day planning phase.

Do not wait for longitudinal source validation before continuing.

Use the Phase 0 documents whenever implementation needs details about an ATS, schema, source, risk or design decision, rather than researching the same subject again.

Build the repo structure and real application architecture, then proceed continuously through:

**foundation and polished UI shell → database/domain model → broad ingestion → company verification → dedupe/lifecycle → classification/eligibility → Fit/Worth/risk → analytics instrumentation → opportunity experience → application tracking → Resume/GitHub intelligence → Gmail/Calendar → preparation pack → browser extension → supported auto-apply → additional source expansion.**

These are an **execution queue**, not isolated gated phases. Work may overlap where sensible.

Do not stop after each item merely to write a report. Continue unless a real technical blocker requires user input.

The overriding philosophy is:

> **Maximum useful internship coverage, excellent personal workflow, strong analytics, polished implementation, and minimal recurring cost. Build enough engineering rigor to make the system trustworthy, but do not import enterprise bureaucracy into a one-user college project.**