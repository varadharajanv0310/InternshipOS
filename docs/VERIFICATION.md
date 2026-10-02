# Verification record

Completed 2 October 2026. Tests use isolated fixtures; the browser smoke check used the running local app with real public-source data and no personal profile.

| Check | Result |
| --- | --- |
| Backend suite | 95 passed; final run 3.38 seconds |
| Frontend suite | 11 passed |
| Extension fixture suite | 8 passed |
| Frontend production build | Passed; app and chart bundles separated |
| Extension content/popup syntax | Passed |
| Live API /health | status ok; SQLite; scheduler enabled; version 0.1.0 |
| Default India technical internship feed | 40 opportunities visible in final browser and API check |
| Live employer registry | 290 employers visible in dashboard |
| Real opportunity detail | HackerRank Software Development Engineer Intern loaded its complete original description and posting link |
| Desktop appearance | Light and dark dashboard checked; no captured browser error logs |
| Mobile layout | 390 × 844 viewport checked; no horizontal document overflow |
| Portable backup | Isolated export/restore round trip tested, including PDF hash validation and secret exclusions |

114 automated tests passed in total. Backend tests cover identity/closure, source safety, eligibility/filters, application transitions, resume facts and PDFs, AI budget concurrency/claim guards, integration matching/idempotence/undo and backup restoration. Extension tests cover field boundaries, opt-ins, wrong-job rejection, CAPTCHA/unknown-field stops and receipt requirements. These are functional fixture checks, not guarantees about every external site.

## Live collection evidence

Bounded public requests returned usable data from Greenhouse, Lever, Ashby, Workday, Unstop, Freehire, Eightfold and Amazon during development. Examples included Razorpay, Meesho, PostHog, NVIDIA and Microsoft. Amazon's India facet was corrected and checked; saved-detail refresh is bounded and a failed or partial request cannot prove a job closed. Some endpoints rate-limit or block automation. Other adapter paths are covered by fixtures/source inspection rather than an exhaustive live board sweep.

## Unverified externally

- Hosted PostgreSQL and production deployment: local Docker engine unavailable; schema, Compose, CI and hosting configuration are supplied.
- Real Google OAuth, personal Gmail/calendar sync and token refresh: owner credentials absent; matching/idempotence/undo tested with fixtures.
- Paid AI inference: no key used or money spent; provider and accounting behavior tested with controlled responses.
- Real employer submissions: fixture-only; unpacked extension requires owner installation and site-specific validation.
- Full-market recall and precision: heuristic classification and source availability can miss or mislabel roles; uncertain entries remain reviewable.

The app currently runs locally, so background collection runs while the backend process is alive. Hosting configuration alone does not establish an always-on service. Keep durable backups in an owner-controlled destination.

Final UI evidence: [desktop overview](screenshots/overview.png). Start/stop and account setup: [SETUP.md](SETUP.md).

## Follow-up verification: 2 October 2026

The subsequent analytics/relevance correction passed 96 backend tests, 11 frontend tests and the frontend production build. Live API confirms scope india with 40 technical internship candidates, compared with 7,785 raw global records. Regression coverage verifies counts, daily discoveries, locations and source contributions share the same scope. The original 114-test result above records the earlier handover; the total is now 115 including the unchanged 8 extension fixtures. No paid AI request or personal Google connection has been made.
