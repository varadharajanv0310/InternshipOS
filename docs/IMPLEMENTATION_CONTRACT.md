# InternshipOS implementation contract

The 2 October 2026 build mandate overrides the historical Phase 0 roadmap. Build continuously; no waiting cohort gate. React/Vite/TypeScript frontend, FastAPI/Python API, SQLAlchemy/PostgreSQL domain. A portable SQLite development fallback is allowed when no local PostgreSQL service exists; deployment targets Postgres. Free scheduled batch execution first, optional persistent worker/VPS. No production cloud resources or personal account actions without credentials/user connection.

## Shared layout and ownership

- `backend/internshipos/`: Python package. Database/core agent owns `db.py`, `models.py`, `domain.py`, `service.py`, `serialize.py`, `seed.py`, core migrations and core tests.
- Ingestion agent owns `ingestion/`, `data/company_seeds.json`, ingestion tests, requirements supplement if needed.
- UI agent owns `frontend/` exclusively, including package, pages, styles, client types and build.
- Root owns `main.py`, `api.py`, `auth.py`, `integrations.py`, `resumes.py`, `ai.py`, `jobs.py`, extension, deployment, requirements, root integration tests and launchers.

## Python domain contract

`db.py` exposes `Base`, `engine`, `SessionLocal`, `get_db()` yielding a SQLAlchemy Session, `init_db()` (idempotent). Config `DATABASE_URL` (Postgres supported, local SQLite default under `data/`). UTC-aware helpers, UUID string IDs, mutable JSON updated by replacement. All modules use SQLAlchemy 2 syntax. No import-time network or ingestion.

Models: Company; CompanySource; FetchRun; Opportunity; JobSource; Snapshot; IdentityDecision; Evidence; Evaluation; Application; ApplicationEvent; Task; Activity; ProfileVersion; Resume; ResumeVersion; Project; Integration; EmailMessage; EmailLink; CalendarLink; Notification; Setting; AIUsage. Use explicit immutable source observations and event history. Keep fields useful to product; JSON for flexible facts/settings, unique scoped IDs. Snapshot content hash; provenance links; corrections add history. No tenants.

`domain.py` exposes `classify(text,title='')`, `evaluate(opportunity,profile)`, safe canonical URL/identity functions, `transition(application,stage,...)` if convenient. Missing evidence is uncertainty, not failed requirement. Fit weights 25/25/10/20/10/10; Worth separate; main score point plus confidence, internal bounds/evidence preserved. No fake personal facts or model-generated pay.

`service.py` provides:

```python
list_opportunities(db, **filters) -> {items,total,page,page_size,facets}
get_opportunity(db, id) -> dict | None
dashboard(db) -> dict
analytics(db, days=30) -> dict
list_companies(db, q='') -> {items,total}
company_detail(db, id) -> dict | None
list_applications(db) -> {items,total}
create_application(db, payload:dict) -> dict
update_application(db, id, payload:dict) -> dict
list_tasks(db) -> {items,total}
save_task(db, payload:dict, id=None) -> dict
get_profile(db) -> dict
save_profile(db, payload:dict) -> dict
get_settings(db) -> dict
save_settings(db, payload:dict) -> dict
list_activity(db) -> {items,total}
undo_activity(db, id) -> dict
save_opportunity(db, id, payload:dict) -> dict
ingest_batch(db, company_source_id, jobs:list[dict], *, complete:bool, error=None, coverage_scope='full', observed_count=None) -> dict
```

`seed.py` exposes `seed_database(db)` (idempotent, creates settings/profile and imports ingestion company seeds once; no fake jobs). Root uses service methods directly. If a function cannot fit this contract, message root before changing it.

Ingestion job dictionaries: `external_id`, `title`, `description`, `description_html`, `location`, `country`, `work_mode`, `apply_url`, `canonical_url`, `requisition_id`, `posted_at`, `deadline`, `employment_type`, `compensation` (kind,label,min,max,currency,period), `skills`, `company_name`, `company_domain`, `raw`, `evidence`. Only healthy complete **unfiltered full-board** runs can infer absence. Partial/query-filtered/challenged returns cannot close. External ID unique inside company-source. Different trusted requisitions separate. Preserve probable duplicate groups and reversible merge evidence.

## HTTP contract

Base `/api`. JSON; `{detail:...}` errors. GET collection returns `{items,total}` except stated. UTC ISO strings. `/health` status. Query keys snake_case. Every mutation persists/audits. No mock fallback in frontend; empty states invite configure/collect.

- GET `/dashboard`; GET `/opportunities?q=&role=&location=&kind=&saved=&min_fit=&sort=&page=1&page_size=40`; GET/PATCH `/opportunities/{id}` (`saved`, `notes`); POST `/capture` with URL/title/company/description/location for browser/manual import.
- GET/POST `/applications`; PATCH `/applications/{id}`. Payload `opportunity_id,stage,resume_version_id,notes`. Stages ready,applied,oa,interview,offer,rejected. Submission is explicit; preparing/filling alone never applied. GET `/applications/{id}/pack`.
- GET/POST `/tasks`; PATCH `/tasks/{id}`; GET `/companies?q=`; GET `/companies/{id}`.
- GET `/analytics?days=30`; GET `/activity`; POST `/activity/{id}/undo`; GET/PATCH `/profile`; GET/PATCH `/settings`.
- GET `/sources` health/current boards; POST `/sources/collect` queues/runs bounded background collection; POST `/sources` manual company/source addition; POST `/sources/discover` registry expansion; GET `/notifications`; PATCH `/notifications/{id}` read/dismiss; POST `/digest`.
- GET `/resumes` => `{items,total,projects}`; POST `/resumes` (name,role_focus); POST `/resumes/{id}/versions` (selected_project_ids,bullets,title); GET `/resume-versions/{id}/download`; GET `/resume-versions/{id}/preview`; POST `/projects/github` (username); PATCH `/projects/{id}` (approved,approved_bullets,...); POST `/ai/{action}` (opportunity_id,resume_id,question; actions analyze,tailor,answer,cover-letter). Clear budget/external-key error; deterministic preparation remains useful.
- GET `/integrations` => configured/connected/status for google/github/AI; GET `/integrations/google/connect` redirects when configured; POST `/integrations/google/poll`; POST `/integrations/google/disconnect`; GET `/emails/review`; POST `/emails/{id}/match` (application_id,event_type); POST `/calendar/sync`; GET `/calendar` domain tasks/events; no invented timestamp.
- POST `/extension/pair` -> loopback-scoped token; GET `/extension/pack?application_id=`; POST `/extension/receipt` (explicit receipt/evidence); separate privileged submit configuration, no automatic submission enabled by default.

Opportunity JSON: `id,title,company:{id,name,domain,verified,logo_url},role_family,opportunity_type,location,work_mode,compensation:{kind,label,min,max,currency,period},posted_at,first_seen,last_verified,deadline,status,saved,fit_score,fit_confidence,worth_score,eligibility,trust_state,risk_reasons,summary,skills,requirements,responsibilities,description,description_html,canonical_url,apply_url,sources[],evaluation:{fit_dimensions[],worth_dimensions[],unknowns[],evidence[]},possible_duplicates[],application_id,notes`.

Applications embed `opportunity`, with `id,stage,created_at,submitted_at,updated_at,resume_version_id,notes,events`. Tasks `id,title,due_at,completed,application_id,opportunity_id,kind,notes`; date precision retained.

Dashboard: `stats` (new_opportunities,saved,applications,active_applications,interviews,companies,sources_healthy), `top_opportunities`, `deadlines`, `recent_activity`, `funnel`, `source_health`, `notifications`, `daily_discoveries`. Analytics: `summary`, `daily_discoveries`, `applications_by_week`, `funnel`, `sources`, `roles`, `locations`, `skills`, `fit_distribution`, `worth_distribution`, `compensation`, `resume_outcomes`, `health`, `ai_usage` (spent,budget,remaining), `definitions`. Every source overlap count uses canonical IDs.

## Revised defaults

Priority boards 6–12h; normal 12–24h; longtail daily; aggregators 1–2/day; saved detail refresh. Gmail 30–60min, read-only. AI monthly hard ceiling default USD2.50 with durable reservation/ledger, optional operations pause at zero. No paid scraping/proxies. No provider keys or personal facts fabricated. Starting registry approximately200 legitimate known companies with independently labelled ATS association status; natural expansion through discovered employer domains and evidence. No generic chatbot.

UI: rich command center, Opportunities split detail/table/card triage, Applications Kanban/table, Companies, Calendar/tasks, substantial Analytics, Resumes/projects, Activity/review, Settings. Light/dark, desktop sidebar/mobile navigation, clear empty/loading/error states, command palette and keyboard actions. Actual backend data only. Sensitive address/legal/browser answers remain local.
