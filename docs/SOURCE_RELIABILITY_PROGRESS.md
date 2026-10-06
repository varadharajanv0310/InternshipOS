# Source reliability repair — 6 October 2026

User priority: improve source reliability first and verify it properly. Keep model/provider cost changes for a later discussion. Google configuration, project approvals and automatic submissions are outside this repair.

## Baseline and evidence

Latest prior snapshot: 573 enabled sources, 183 complete, 224 partial, 157 error, nine quarantined; 205 personal-feed opportunities. Configured cloud schedule is every two hours, while recent actual scheduled runs were about eight hours apart.

Private raw snapshots and reproducible live experiments belong under `data/private/source-reliability/`. Public notes record causes and endpoint evidence without credentials or resume/profile contents. A lower error count alone is not proof of recovered coverage.

## Checklist

- [x] Export a fresh live source/fetch-run baseline and group failures by provider/cause.
- [x] Repair shared HTTP/collector failures and coverage-continuation bugs.
- [x] Reconcile obsolete source endpoints with evidence from official employer sites (eight repairs, two canonical bindings; unresolved candidates remain documented).
- [x] Make health, due times, retries and collection heartbeat reflect actual coverage.
- [x] Test representative live endpoints and recover known relevant internships (Kaleris Chennai; actual Internshala markup).
- [x] Run targeted regression tests and existing required checks (211 backend, 13 frontend, 16 extension; frontend production build).
- [ ] Deploy existing project, run cloud collection and verify live post-repair results.
- [ ] Document remaining blocked/unsupported sources and exact next actions.

Parallel ownership: root coordinates audit, worker and deployment; coverage collector work owns adapters; source registry work owns discovery and endpoint evidence; health work owns source health and operational display. Existing research, approved resumes and private credentials remain preserved.

## Incremental validation

Fresh baseline: 573 enabled sources; 183 complete, 224 partial, 157 error, nine quarantined. Raw source and latest-run evidence are saved privately. Of the failures, 72 have no supported public JobPosting markup, nine exceed the response-size allowance, six reject our previous GET-only configured-feed path, and 17 Internshala queries have changed title markup. HTTP challenges and genuinely moved endpoints are separate causes.

First read-only benchmark: 15 sources checked, 13 returned their configured scope without errors. Kaleris yielded six Chennai software internships with descriptions, including R-100658 from the user's screenshot. Microsoft hit the bounded page limit; HPE changed its reported total during the scan and remains incomplete. These results are not a claim of exhaustive coverage or a production database update. Subsequent changes and the hosted repair scan will be recorded in the final validation document.

Historical target-query labels will be corrected only from a matching persisted, completed, error-free board fetch. This correction preserves original timestamps and full-board closure restrictions; it is explicitly separate from newly recovered live coverage.
