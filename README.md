# InternshipOS

A personal internship workspace with broad public-source collection, evidence-aware matching, application tracking and preparation. The app is implemented and runs locally at **http://127.0.0.1:5173**.

## Start

```powershell
.\Start-InternshipOS.ps1 -Setup
```

Later starts can omit `-Setup`. Stop with `Stop-InternshipOS.ps1`. Main prerequisites: Python 3.11–3.13 and Node 22+. Optional JobSpy uses a separate Python 3.11 environment. Local data stays in `data/`; PostgreSQL is the hosted target.

Start by adding actual profile facts in Settings, reviewing GitHub projects, and creating a factual resume version. The app starts without invented personal facts. Unknown Fit/Worth remains unknown until matching evidence exists.

## Included

- 200 trusted employer seeds, independently verified ATS associations and an expanding discovered-company registry.
- 14 structured ATS families, custom/public HTML paths, internship discovery platforms, optional JobSpy and capture fallback. Source failures are visible.
- Conservative scoped identity, provenance, immutable observations, reversible corrections and closure guards.
- Rich command center, India/CSE internship feed, advanced filters and saved views, applications board/table, companies, calendar/tasks, analytics, Resume Vault, activity and settings.
- Separate eligibility, Fit/confidence, Worth, urgency and trust. No invented pay or resume achievements.
- Prepared application packs, deterministic versioned PDF resumes and reviewed GitHub project facts.
- Own read-only Gmail OAuth, conservative recruiting-mail matching and a dedicated Calendar with exact-date handling.
- Manifest V3 capture/autofill companion; supported opt-in auto-apply with missing-answer/CAPTCHA/job-identity/receipt guards.
- Optional AI provider boundary and serialized hard monthly spending reservations; normal operation works without AI.
- Portable backup export/restore, free batch scheduling, PostgreSQL schema and Vercel/optional Compose deployment configuration.

## Setup and limits

See [setup instructions](docs/SETUP.md) for Google, AI, extension, backups, hosting and test commands. See [current build status](docs/BUILD_STATUS.md) and [verification results](docs/VERIFICATION.md).

The local app is running with real public-source results. Google account connection, paid AI quality, live employer submission and hosted PostgreSQL/deployment have not been exercised with the owner's accounts. They require the owner's credentials or external environment. Free hosting configurations are included but no external service was purchased or deployed.

## Project

`frontend/` contains React/Vite/TypeScript. `backend/internshipos/` contains FastAPI, SQLAlchemy domain/services, ingestion, integrations and workers. `extension/` contains the browser companion. `docs/` contains the accepted build mandate, setup and status. `.github/workflows/` contains tests and scheduled collection.

The completed Phase 0 research is retained under [research/](research/README_PHASE_0.md), with its original [progress record](PHASE_0_PROGRESS.md). Its historical roadmap is reference only; the revised [build mandate](docs/BUILD_MANDATE.md) governs this implementation.
