# Source reliability repair — 6–7 October 2026

User priority: improve source reliability first and verify it properly. Keep model/provider cost changes for a later discussion. Google configuration, project approvals and automatic submissions are outside this repair.

## Baseline and evidence

Latest prior snapshot: 573 enabled sources, 183 complete, 224 partial, 157 error, nine quarantined; 205 personal-feed opportunities. Configured cloud schedule is every two hours, while recent actual scheduled runs were about eight hours apart.

Private raw snapshots and reproducible live experiments belong under `data/private/source-reliability/`. Public notes record causes and endpoint evidence without credentials or resume/profile contents. A lower error count alone is not proof of recovered coverage.

## Checklist

- [x] Export a fresh live source/fetch-run baseline and group failures by provider/cause.
- [x] Repair shared HTTP/collector failures and coverage-continuation bugs.
- [x] Reconcile obsolete source endpoints with evidence from official employer sites (eight endpoint repairs, four guarded configuration repairs and three canonical bindings; unresolved candidates remain documented).
- [x] Make health, due times, retries and collection heartbeat reflect actual coverage.
- [x] Test representative live endpoints and recover known relevant internships (Kaleris Chennai; actual Internshala markup).
- [x] Run targeted regression tests and existing required checks (211 backend, 13 frontend, 16 extension; frontend production build).
- [x] Deploy existing project, run cloud collection and verify live post-repair results.
- [x] Document remaining blocked/unsupported sources and exact next actions.

Parallel ownership: root coordinates audit, worker and deployment; coverage collector work owns adapters; source registry work owns discovery and endpoint evidence; health work owns source health and operational display. Existing research, approved resumes and private credentials remain preserved.

## Incremental validation

Fresh baseline: 573 enabled sources; 183 complete, 224 partial, 157 error, nine quarantined. Raw source and latest-run evidence are saved privately. Of the failures, 72 have no supported public JobPosting markup, nine exceed the response-size allowance, six reject our previous GET-only configured-feed path, and 17 Internshala queries have changed title markup. HTTP challenges and genuinely moved endpoints are separate causes.

First read-only benchmark: 15 sources checked, 13 returned their configured scope without errors. Kaleris yielded six Chennai software internships with descriptions, including R-100658 from the user's screenshot. Microsoft hit the bounded page limit; HPE initially reported inconsistent totals, later shown to be a paging-contract mismatch. These initial results were not a claim of exhaustive coverage or a production database update. Subsequent changes and hosted checks are recorded below and in the final validation document.

Historical target-query labels will be corrected only from a matching persisted, completed, error-free board fetch. This correction preserves original timestamps and full-board closure restrictions; it is explicitly separate from newly recovered live coverage.

## Resume state — 7 October 2026

- [x] Deploy and push the tested continuation/cursor, availability and configuration-guard follow-ups: `4699c7b`, `700d2e5`, `4953ba9`.
- [x] Complete corrected 36-source cloud scan: run `37651627676`; 36 boards returned seven complete, six complete for their requested scope, ten partial and 13 errors, with zero worker errors. These are result statuses, not 36 recovered connections.
- [x] Verify local checks: 224 passed and one PostgreSQL-only check skipped locally. The prior cloud run completed 249 checks including PostgreSQL.
- [x] Verify and apply four guarded configuration repairs for Atlassian, Publicis Groupe, Persistent Systems and GitHub, preserving source identities and owner settings.
- [x] Queue the four-source live validation batch: job `8faf6b493e2c4cb088e9519f0c37ef70`, cloud run `37653879472`.
- [x] Save a rerunnable remaining-source report generator and initial public CSV/priorities document; private snapshots contain the detailed audit evidence.
- [x] Inspect final four-source scan results and regenerate the remaining-source report from the final hosted snapshot.
- [x] Resolve the Internshala Chennai parser/identity mismatch with evidenced record handling and fresh regional verification.
- [x] Finish the narrowly scoped Salesforce public-response size repair and record fresh collection results.
- [x] Complete the final deployment/live verification checklist after the above results are recorded; unresolved sources remain explicit.

Read-only resumed hosted snapshot at 16:20 UTC: 579 enabled sources, 198 complete, 177 complete for the requested scope, 68 partial, 135 error and one quarantined. There are 158 historical scope-label corrections, reported separately from successful fresh collection. The schedule was on time, but 423 sources were due, 255 stale and 28 awaiting a retry.

Subsequent bounded Workday probes confirmed that later pages can return zero as a total-count sentinel while still supplying distinct jobs (HPE, BrowserStack and Epicor). The adapter fix retains a fresh first-page count, checks resumed final-scope heads, and rejects real positive-count contradictions, invalid/repeated records and early empty pages. Targeted verification passed 102 tests including 18 new contract cases. This follow-up was subsequently deployed and verified through fresh checks; existing health history was preserved.

A later 16-source concurrent verification completed with zero worker errors and one real PostgreSQL retry. HPE (two routes), BrowserStack, G-Research, Sysco (two routes) and RBC returned successful requested-scope coverage. Epicor's remaining error was traced through four public pages to a separate identity bug: 74 unique posting paths were collapsed to 32 first-bullet values because that tenant puts location before requisition ID. Its narrow parser/detail-lookup repair preserves distinct duplicate-post paths and existing normal IDs; 107 targeted checks passed including five new identity cases. The repair was subsequently deployed and Epicor passed fresh verification. Old location-valued IDs still require historical review rather than destructive merging.

Durable outputs: `docs/SOURCE_RELIABILITY_REMAINING.csv`, `docs/SOURCE_RELIABILITY_REMAINING.md`, `docs/SOURCE_RELIABILITY_ENDPOINTS.md`; rerun `data/private/source-reliability/generate_remaining_report.py` with `--snapshot <final-prefix>-sources.json` after a future read-only export. No production credentials or profile facts belong in these public files. This repair and verification batch is complete; the remaining source backlog is documented separately.

### Earlier checkpoint — completed by final verification below

Commit `9416b92` was pushed and deployed. At that earlier checkpoint, 266 local checks passed and three isolated PostgreSQL checks were skipped. The earlier 48-source run saved 47 source results and exposed one actual PostgreSQL deadlock; its durable job remains failed in history. Bounded transaction retries and nonzero CLI failure exits address that concrete issue. Workday later-page zero-count sentinels and Internshala's explicit terminal regional page have regression coverage. The later final revision's CI and deployment results are recorded below.

The concurrent 16-source production verification (`7cc1eb9e9fd548ab97a708801b9981f7`) subsequently finished with zero worker errors and one actual PostgreSQL retry. Fresh frontend and Epicor checks also completed successfully. Private request/result files use prefix `final-concurrent-2026-10-07`. This repair batch's deployment and validation checklist is complete; unsupported integrations, access restrictions, bounded continuation and stale queues remain explicit.

### Final verified checkpoint — 7 October 2026, 17:45 UTC

- [x] Final commit `afddf2e` deployed; Vercel reports production ready for `internshipos-ikv6vvvo4`.
- [x] Local required checks: 273 passed; three isolated PostgreSQL checks skipped locally.
- [x] Cloud CI `37659340840`: 276 backend checks including PostgreSQL, 13 frontend checks and 16 extension checks, totaling 305 passed.
- [x] Concurrent 16-source job `7cc1eb9e9fd548ab97a708801b9981f7` finished with zero worker errors and one actual PostgreSQL deadlock recovery; results were 14 requested-scope successes, one partial and one Epicor error. These were statuses, not 16 recovered connections.
- [x] Fresh frontend regional check (`1a7...`) returned successful requested-scope coverage with zero worker errors.
- [x] Final Epicor check (`d415...`) returned successful requested-scope coverage with zero worker errors after its posting-ID fix.
- [x] Final four-source Workday check (`381daeca377c439f92f99f7f6be8f379`) completed the Visa, Intel and PayPal requested scopes; Accenture reached the explicit page limit and remains partial. Zero worker errors; no transaction retries needed.
- [x] Export final protected read-only snapshot and regenerate the public remaining-source CSV/priorities report.

Final hosted state: **569 enabled sources; 384 successful (199 full inventory, 185 requested scope), 71 partial, 113 error and one quarantined**. There are **97 Broken, 16 Blocked and one Needs review** health labels. The **158 historical scope-label corrections** and **11 superseded aliases** are reported separately from successful fresh checks and are not added to recovery counts.

The final queue still contains **385 due sources, 226 stale sources and 21 awaiting backoff/retry**. The public CSV records **185 enabled unsuccessful sources** with public URLs, causes, actions and due times. Highest remaining priorities are unsupported public integrations, stale/unfinished collection, and review of historical location-valued IDs. Access restrictions and unproven coverage remain visible; no claim is made that every useful internship is found.

Private resume evidence: `final-all-fixes-2026-10-07-sources.json`, `final-all-fixes-2026-10-07-summary.json` and `final-all-fixes-2026-10-07-remaining-audit.json`, plus `cloud-job-381daeca377c439f92f99f7f6be8f379.json`. To refresh the public backlog after a later scan, rerun the saved generator against its new source snapshot. This batch did not change model selection or credentials, and automatic application submission remains outside its scope.
