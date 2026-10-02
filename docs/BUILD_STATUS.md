# Build status

3 October 2026 - hosted app available at https://internshipos.vercel.app, backed by Neon PostgreSQL. Login and main authenticated endpoints verified. Cloud collection is scheduled every six hours; first scan is in progress. Google and paid AI remain unconfigured. The original local archive is preserved.

Completed: 200 verified employer seeds with independently labelled ATS associations; 14 structured ATS families, custom/discovery sources and optional JobSpy; canonical identity/provenance/closure guards; India/CSE default feed; configurable collection and saved-detail refresh; employer verification and registry growth; deterministic eligibility/Fit/Worth; nine responsive product pages, advanced filters and saved views; application history/preparation; structured immutable resume versions and portable PDF; GitHub review inventory; first-party Gmail/Calendar; guarded extension capture/fill/opt-in submission; monthly AI reservations/provider boundary; portable backup export and tested restore; deployment/CI/launch configuration.

Verification: 96 backend tests pass; 11 frontend tests and production build pass; 8 extension fixture tests pass — 115 automated tests total. Real public-source collection is running. Final desktop light/dark and mobile browser checks passed, with no captured browser errors. No personal Google account, paid inference or real application submission was used.

Local persistence is SQLite. PostgreSQL schema/bootstrap and CI service configuration are ready; Docker's local Linux engine was unavailable, so a live PostgreSQL deployment is unverified. External deployment, OAuth and AI access require the owner's accounts/keys. The app works without those optional connections.

## Completion checklist

- [x] Implementation, local launch and collection.
- [x] Backend, frontend and extension fixtures; frontend production build.
- [x] Final desktop/mobile browser checks, real full-description detail and live API smoke check.
- [x] README, setup, third-party notices, verification record and saved dashboard screenshot.
- [ ] Owner profile, approved project/resume facts and optional Google/AI credentials.
- [ ] Owner browser extension installation and validation on actual supported employer forms.
- [ ] Hosted PostgreSQL, deployment/CI accounts, production authentication and backup destination if remote operation is wanted.

Public-site success is variable and heuristic classifications can require review. No claim of exhaustive coverage or universal auto-apply is made. See [verification](VERIFICATION.md) and [setup](SETUP.md). Historical Phase 0 is complete; PHASE_0_PROGRESS.md remains its separate record.

## Follow-up: analytics and role relevance

2 October 2026: analytics now defaults to India technical internship candidates, with an explicit all-global-records selector. Opportunity charts and source contributions use the same selected scope. Global raw records remain stored and are labelled separately. The dashboard discovery chart now uses relevant India roles. Removed 3D Artist false positives and corrected mobile/testing/.NET title classification ahead of employer AI boilerplate. Current feed: 40 candidates. Added CURRENT_INDIA_ROLES.md/CSV and GOOGLE_CONNECTION.md. OpenAI remains unconfigured and disabled; Google remains disconnected. Backend 96 tests and frontend 11 tests/build passed for this change.


## Hosting update, 3 October 2026

Vercel production: https://internshipos.vercel.app . Neon PostgreSQL migrated with personal India/review shortlist and resume-based profile. Private GitHub repository created, Vercel Git integration connected, production origins/secrets configured. Authenticated main read endpoints verified; PostgreSQL health returned 200. 118 automated tests passed (99 backend, 11 frontend, 8 extension), including cloud PostgreSQL bootstrap. Collection configured every six hours; first run status tracked in HOSTING_STATUS.md. Google/AI credentials still absent. See SEARCH_POLICY.md and PREVIOUS_PROJECT_REUSE.md for targets and reuse.
