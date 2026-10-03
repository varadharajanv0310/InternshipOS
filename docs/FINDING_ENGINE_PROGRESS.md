# Finding engine and application repair

Updated 3 October 2026. User authorized implementation of the seven-step plan. No real employer submissions have been made. This extends InternshipOS; the previous tracker supplies source candidates and editable employer preferences, not its feed, fit formula or application odds.

- [x] HTTP compression and isolated JobSpy launch fixed and regression-tested. Live LinkedIn check returned five roles without error; Windows JSON encoding fixed too.
- [x] Source health distinguishes successful, partial, blocked, broken, stale and identity review. Partial inventory cannot prove closure.
- [x] Previous employer/source registry restored as unverified candidates; 404 board candidates and 77 career-page references. All 53 snapshot leads reconciled: 24 live verified, 20 outside policy, 9 unresolved.
- [x] Bengaluru/Chennai/remote India/India-unspecified policy shared across collection, feed, analytics and preparation. Other cities and PhD-only titles excluded from the personal feed.
- [x] Company-priority default ordering, explanations and owner overrides. Fit remains a separate assessment.
- [x] Continuation cursors for generic pages, Workday, Oracle and Eightfold; fair scheduling and separate board/detail clocks. LinkedIn/Indeed, Internshala, GitHub and existing structured sources complement each other.
- [x] Approved application queue: freshness, eligibility, employer/provider verification, immutable pack fingerprint, duplicate check, daily attempt limit, single lease and exact resume receipt checks.
- [x] Extension queue executor: explicit batch start, local facts snapshot, supported provider permissions, pause for unknown answers/challenges/missing receipts; restart cannot silently retry an attempted application.
- [x] Local tests and frontend production build pass: 110 backend, 11 frontend, 16 extension tests (137 total).
- [ ] Publish current changes and verify hosted endpoints and scheduled worker.
- [x] Existing connected repository made public; 608 historical Git objects checked with no known credential matches.

Live submission is off. Actual employer forms, browser permissions and personal answers still require owner setup; fixtures do not prove compatibility with every live form. The browser executor needs an open browser and paired extension; Vercel does not host a browser. Unsupported sites and unresolved source checks remain visible rather than being counted as healthy coverage.

Collection is scheduled every two hours, capped at 96 due sources per run, with six concurrent collectors and bounded continuation. The current enabled registry exceeds one batch: individual sources can lag their preferred cadence. This is scheduled background collection, not continuous exhaustive searching.
