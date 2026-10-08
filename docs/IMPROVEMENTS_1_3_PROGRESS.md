# Discovery, freshness and shortlist improvements — 8 October 2026

User authorized implementation of remaining items 1–3: source coverage, collection freshness and shortlist accuracy. Preserve the current Vercel/Neon project, personal location policy, company priority, source preferences, approved facts and private credentials. AI/Google setup and live application submission remain outside this work.

## Baseline

Fresh pre-change snapshot (8 October, 06:30 UTC): 569 enabled sources; 212 full inventory successes, 200 requested-scope successes, 49 partial, 107 error and one identity review. Queue: 235 due, 124 stale, 21 in retry backoff. The earlier 7 October snapshot had 385 due and 226 stale; those earlier counts must not be used as the baseline for this change.

## Work checklist

- [x] Save a fresh source and shortlist baseline with explicit definitions.
- [ ] Audit every remaining integration category and prioritize relevant regional employers.
- [x] Add reusable supported public integrations and evidence-backed endpoint replacements.
- [ ] Repair specific remaining request/detail/response-size issues where actual public responses establish the contract.
- [ ] Complete bounded partial inventory/detail continuations and verify live results.
- [x] Increase bounded collection capacity and prioritize overdue useful sources without starving other enabled sources.
- [ ] Measure and reduce the due/stale backlog; distinguish worker timing from source freshness.
- [ ] Resolve proven mirrored-role duplicates while preserving provenance, application/resume history and distinct requisitions.
- [x] Explain eligibility uncertainty with the exact missing or conflicting requirements.
- [x] Add reversible owner exclusions for roles and companies consistently across the personal shortlist.
- [x] Show and enforce appropriate liveness review before recommendation/preparation.
- [ ] Run meaningful regression checks and required builds.
- [ ] Deploy to the existing project and verify production behavior.
- [ ] Save final evidence, precise remaining gaps and resumable next actions.

## Ownership and evidence

Fresh baseline at 06:30 UTC on 8 October: 569 enabled; 212 full successes, 200 requested-scope successes, 49 partial, 107 errors, one identity review. There were 235 due, 124 stale and 21 in backoff. The last worker completion was 01:09 UTC, over five hours earlier. The strict technical India feed had 477 records before duplicate reconciliation; this is not a count of uniquely eligible useful internships. Evidence prefix: `improvement-baseline-2026-10-08`.

Read-only official-route audit completed for 33 obsolete/restricted/DNS candidates. Concrete binding evidence and scope cautions are recorded in `OFFICIAL_SOURCE_ALTERNATIVES_2026-10-08.md`. Eighteen focused public LinkedIn tests pass. With pacing and the normal 40-detail allowance, two live India queries each retained 30 listings and completed all targeted descriptions (9 and 10) in 16.4 and 18.2 seconds, without rate-limit errors. These are bounded discovery windows, not full LinkedIn inventory proofs; future rate limits remain visible.

Local combined validation currently passes 350 backend checks (four isolated PostgreSQL checks deferred to CI), 14 frontend checks and 16 extension checks, plus the frontend production build. A subsequent clean-startup regression explicitly creates both queue and worker-lease tables; final totals will be recorded after integration and CI. Runtime `backend/data/` is now excluded from Git and deployment uploads so a generated local authentication secret cannot be published.

Source expansion owns collection/discovery adapters and repair manifest. Freshness work owns scheduler, source clocks and collection workflow. Shortlist work owns evaluation, canonical identity, exclusions and opportunity UI. Root coordinates official endpoint alternatives, experiments, deployment and production checks.

Public notes must not include credentials, applicant facts, raw configuration bodies or copied personal documents. Private reproducible probes and API snapshots go under `data/private/source-reliability/`. Access restrictions are not bypassed, and a successful workflow is not a claim that every source succeeded. Partial/query scans cannot close jobs based on absence.
