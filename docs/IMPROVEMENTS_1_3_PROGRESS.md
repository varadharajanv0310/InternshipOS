# Discovery, freshness and shortlist improvements — 8 October 2026

User authorized implementation of remaining items 1–3: source coverage, collection freshness and shortlist accuracy. Preserve the current Vercel/Neon project, personal location policy, company priority, source preferences, approved facts and private credentials. AI/Google setup and live application submission remain outside this work.

## Baseline

Fresh pre-change snapshot (8 October, 06:30 UTC): 569 enabled sources; 212 full inventory successes, 200 requested-scope successes, 49 partial, 107 error and one identity review. Queue: 235 due, 124 stale, 21 in retry backoff. The earlier 7 October snapshot had 385 due and 226 stale; those earlier counts must not be used as the baseline for this change.

## Work checklist

- [x] Save a fresh source and shortlist baseline with explicit definitions.
- [x] Audit every remaining integration category and prioritize relevant regional employers.
- [x] Add reusable supported public integrations and evidence-backed endpoint replacements.
- [x] Repair specific remaining request/detail/response-size issues where actual public responses establish the contract.
- [x] Exercise bounded inventory/detail continuations and record successful and unresolved live outcomes.
- [x] Increase bounded collection capacity and prioritize overdue useful sources without starving other enabled sources.
- [x] Measure and reduce the due/stale backlog; distinguish worker timing from source freshness.
- [x] Resolve proven mirrored-role duplicates while preserving provenance, application/resume history and distinct requisitions.
- [x] Explain eligibility uncertainty with the exact missing or conflicting requirements.
- [x] Add reversible owner exclusions for roles and companies consistently across the personal shortlist.
- [x] Show and enforce appropriate liveness review before recommendation/preparation.
- [x] Run meaningful regression checks and required builds.
- [x] Deploy to the existing project and verify production behavior.
- [x] Save final evidence, precise remaining gaps and resumable next actions.

## Ownership and evidence

Fresh baseline at 06:30 UTC on 8 October: 569 enabled; 212 full successes, 200 requested-scope successes, 49 partial, 107 errors, one identity review. There were 235 due, 124 stale and 21 in backoff. The last worker completion was 01:09 UTC, over five hours earlier. The strict technical India feed had 477 records before duplicate reconciliation; this is not a count of uniquely eligible useful internships. Evidence prefix: `improvement-baseline-2026-10-08`.

Read-only official-route audit completed for 33 obsolete/restricted/DNS candidates. Concrete binding evidence and scope cautions are recorded in `OFFICIAL_SOURCE_ALTERNATIVES_2026-10-08.md`. Eighteen focused public LinkedIn tests pass. With pacing and the normal 40-detail allowance, two live India queries each retained 30 listings and completed all targeted descriptions (9 and 10) in 16.4 and 18.2 seconds, without rate-limit errors. These are bounded discovery windows, not full LinkedIn inventory proofs; future rate limits remain visible.

Cloud validation passed for `eb1e126`: 367 backend checks including isolated PostgreSQL checks, 14 frontend checks, 16 extension checks and the frontend production build. Local backend checks passed 363 with four PostgreSQL-only skips. Runtime `backend/data/` is excluded from Git and deployment uploads so a generated local authentication secret cannot be published. A later real command-line worker check exposed the startup issue described below; its follow-up validation is separate.

## Hosted changes and verification

Guarded bootstrap created the worker-lease table, added ten source routes, linked eighteen obsolete/reference aliases and applied three source configurations. It preserved disabled preferences, cadence and private credentials. The repair manifest now contains eleven new replacement declarations, seven new canonical bindings and three new config repairs, alongside earlier records.

Reconciliation applied to 494 useful-location technical internship candidates: 273 actual historical description dates recovered, seven exact-URL visibility aliases created and seven historical Workday identity discrepancies flagged. No opportunity/source rows or application references were deleted or moved; a private before-image and dry-run are saved. Ambiguous LinkedIn/official-board mirrors and distinct requisitions remain separate.

Live API verification on 8 October at 19:47 IST passed company ordering, strict location decisions, eligibility reasons, separate evidence clocks, role/company exclusion and restoration, preserved owner exclusions, unchanged application history, blocked stale Ready preparation and dashboard freshness gates. Automatic submission remained off. Deployment `dpl_ANmCtGdcZc26bZxTougQwoPqDwGJ` was Ready on the existing domain.

The first durable production route run checked all 35 requested sources in 366.9 seconds: 27 successful reads, seven partial and one error, with no unrecovered persistence errors. The catch-up checked 136 due sources in 380.1 seconds: 82 successful, eight partial and 46 errors, with no worker errors or deferred work. Actual parallel traffic exposed two LinkedIn source timeouts and an anonymous-card error; follow-up fixes cap paced LinkedIn searches at two per collection wave and retain valid cards while keeping unverifiable cards explicitly partial. Live verification also caught commercial GTM/financial-analyst roles inheriting software-company boilerplate; those title categories are now excluded from the technical shortlist.

The six-source follow-up finished in 98.9 seconds with two successful scope reads, three partial and one error, no worker errors and no deferred work. State Street and FIS completed the verified target scope; Accenture remained time-limited. Two LinkedIn queries reached their detail budget, and an anonymous-card query had no usable employer identity. These unresolved scans retain their real health state and cannot prove closure.

At 14:32 UTC (20:02 IST), board health showed 564 enabled sources: 212 full successes, 216 target-scope successes, 47 partial, 88 failed and one needing review. There were 21 due, zero stale and no overdue successful sources. At 14:42 UTC, another 45 checks had become due as their cadence/retry times arrived: 66 due, with zero stale successful or partial sources and 16 stale failing sources. Backlog is a moving observation, not a permanent zero. Twenty sources were in retry backoff.

Fourteen previously unsuccessful stable source IDs became successful with a later board check compared with the fresh baseline, and nine newly registered sources are successful. Twenty-six aliases are now superseded (eleven pre-existing plus fifteen newly retired after replacement evidence). These measures are distinct, and retirement is not a recovered feed. Other scheduled checks ran between the morning baseline and the afternoon snapshot; the full difference is not attributable solely to this code.

An actual owner-protected AlphaGrep role recheck completed at 14:41 UTC. It advanced the full-description clock only after an exact official read, preserved board inventory state/cursors/preferences and left applications unchanged. Queueing did not advance evidence; automatic submission remained off. The live UI showed the recheck control, eligibility explanation, separate clocks and restored exclusions.

Cloud workflow `37794788880` exposed a module-entry startup crash: `python -m internshipos.jobs` registered queue tables again when database initialization imported the same module by package name. Revision `55ca8f5` moves durable table definitions into a shared model module used by both entry paths. The actual command-line entry against an empty isolated fixture now has a regression; focused worker/persistence checks pass 26 with three PostgreSQL-only skips. Cloud CI `37795546223` passed 368 backend, 14 frontend and 16 extension checks (398 total) plus the frontend build; the complete local backend suite passed 364 with four PostgreSQL-only skips. Production deployment `dpl_DjimeWGzMxXYhcmHiy3x96yJyFU2` is Ready. Fixed cloud collector run [37795548382](https://github.com/varadharajanv0310/InternshipOS/actions/runs/37795548382) completed successfully: 68 sources in 283.0 seconds, 37 successful, 23 partial, eight errors, zero worker errors and no deferred work. These are actual cloud reads of the existing production database, not isolated fixtures.

## Final snapshot and remaining work

Saved at **14:57:19 UTC / 20:27 IST on 8 October**: 564 enabled boards, **429 successful** (212 full inventory and 217 target scope), **47 partial, 87 failed** (77 broken and ten blocked), and **one needing review**. One partial scan was due; zero successful sources were overdue. Sixteen failing sources were stale, with zero stale successful or partial sources; 27 sources were in retry backoff. No source had never been checked. The last actual inventory collection finished at 14:55:42 UTC; no worker lease remained active. Cadence/retry arrivals will change these figures.

Compared with the fresh baseline, 15 previously unsuccessful stable IDs now have a later successful board observation; nine newly registered sources are successful. The 26 superseded aliases retain history, and the 158 earlier scope-label corrections are separate from fresh recoveries. Private artifacts use the `improvements-cloud-final-2026-10-08` prefix, plus the masked cloud-run log/result and exact-role/exclusion verification files.

The public [remaining-work report](SOURCE_RELIABILITY_REMAINING.md) and [per-source CSV](SOURCE_RELIABILITY_REMAINING.csv) retain **135 enabled non-successful sources**. Of these, 59 need supported public integrations, 48 have unfinished inventory/detail evidence, 12 have obsolete endpoints, ten have access restrictions, two need employer identity review, and four have other request/response/DNS/upstream issues. Categories describe causes and differ from the status counts. Some audited custom pages do not expose a readable public inventory; no complete coverage or exhaustive useful-internship recall is claimed.

Next source-specific priorities: implement the evidenced MoEngage Trakstar contract; inspect declared public inventory feeds for the remaining custom providers; continue Accenture and other bounded scans; verify replacement ownership and native identities before accepting changed endpoints. Recheck the seven historical Workday identity flags using original posting evidence. Keep ambiguous mirrors distinct and preserve application references. Optional project-fact approval, Google/AI configuration and live application submission remain outside these repairs.

All 66 unsupported-integration entries were audited, including saved public pages and actual bounded reads. Fifty-one still lacked a supported readable inventory in that experiment; the per-source list is in `SOURCE_COVERAGE_EXPANSION_2026-10-08.md`. This is not a claim that every failing source or custom provider has been implemented. Access restrictions, incomplete pages and unproved employer identities remain visible.

Source expansion owns collection/discovery adapters and repair manifest. Freshness work owns scheduler, source clocks and collection workflow. Shortlist work owns evaluation, canonical identity, exclusions and opportunity UI. Root coordinates official endpoint alternatives, experiments, deployment and production checks.

Public notes must not include credentials, applicant facts, raw configuration bodies or copied personal documents. Private reproducible probes and API snapshots go under `data/private/source-reliability/`. Access restrictions are not bypassed, and a successful workflow is not a claim that every source succeeded. Partial/query scans cannot close jobs based on absence.
