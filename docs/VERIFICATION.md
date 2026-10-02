# Verification record

Updated 3 October 2026. Tests use isolated fixtures; the browser smoke check used the running local app with real public-source data and no personal profile.

| Check | Result |
| --- | --- |
| Backend suite | 99 passed; latest local run 3.82 seconds; cloud suite passed |
| Frontend suite | 11 passed |
| Extension fixture suite | 8 passed |
| Frontend production build | Passed; app and chart bundles separated |
| Extension content/popup syntax | Passed |
| Live API /health | Hosted /api/health: status ok; PostgreSQL; API scheduler disabled; external GitHub collector |
| Default India technical internship feed | Hosted snapshot: 46 default opportunities; 32 with sufficient scoring evidence |
| Live employer registry | 323 migrated employer/discovery records; old local browser snapshot had 290 employers |
| Real opportunity detail | HackerRank Software Development Engineer Intern loaded its complete original description and posting link |
| Desktop appearance | Light and dark dashboard checked; no captured browser error logs |
| Mobile layout | 390 × 844 viewport checked; no horizontal document overflow |
| Portable backup | Isolated export/restore round trip tested, including PDF hash validation and secret exclusions |

118 automated tests passed in total (99 backend, 11 frontend, 8 extension). Backend tests cover identity/closure, source safety, eligibility/filters, application transitions, resume facts and PDFs, AI budget concurrency/claim guards, integration matching/idempotence/undo and backup restoration. Extension tests cover field boundaries, opt-ins, wrong-job rejection, CAPTCHA/unknown-field stops and receipt requirements. These are functional fixture checks, not guarantees about every external site.

## Live collection evidence

Bounded public requests returned usable data from Greenhouse, Lever, Ashby, Workday, Unstop, Freehire, Eightfold and Amazon during development. Examples included Razorpay, Meesho, PostHog, NVIDIA and Microsoft. Amazon's India facet was corrected and checked; saved-detail refresh is bounded and a failed or partial request cannot prove a job closed. Some endpoints rate-limit or block automation. Other adapter paths are covered by fixtures/source inspection rather than an exhaustive live board sweep.

## Unverified externally

- Production API uses Neon PostgreSQL, with live schema/data migration and authenticated endpoint checks completed. GitHub CI passed backend tests, PostgreSQL bootstrap, frontend build/tests and extension tests.
- Real Google OAuth, personal Gmail/calendar sync and token refresh: owner credentials absent; matching/idempotence/undo tested with fixtures.
- Paid AI inference: no key used or money spent; provider and accounting behavior tested with controlled responses.
- Real employer submissions: fixture-only; unpacked extension requires owner installation and site-specific validation.
- Full-market recall and precision: heuristic classification and source availability can miss or mislabel roles; uncertain entries remain reviewable.

The hosted app is https://internshipos.vercel.app. PostgreSQL health, login, authentication rejection, profile, dashboard, opportunity list, analytics and settings endpoints passed. The default hosted query returned 46 opportunities: 32 had both numeric Fit/Worth scores; the remaining listings lacked sufficient evidence for one or both scores. Eligibility was unclear for 44 and probably eligible for 2. These are descriptive signals, not hiring probabilities. Collection is configured in private GitHub Actions every six hours; see HOSTING_STATUS.md for the first run outcome. Keep durable backups in an owner-controlled destination.

Final UI evidence: [desktop overview](screenshots/overview.png). Start/stop and account setup: [SETUP.md](SETUP.md).

## Follow-up verification: 2 October 2026

The subsequent analytics/relevance correction passed 96 backend tests, 11 frontend tests and the frontend production build. Live API confirms scope india with 40 technical internship candidates, compared with 7,785 raw global records. Regression coverage verifies counts, daily discoveries, locations and source contributions share the same scope. The original 114-test result above records the earlier handover; the total is now 115 including the unchanged 8 extension fixtures. No paid AI request or personal Google connection has been made.
