# Source reliability validation — 6–7 October 2026

The acceptance target is usable, inspectable public-source coverage. Counts of successful requests alone do not show that the right internships were recovered.

## Original observation

573 enabled sources: 183 complete, 224 partial, 157 errors, nine quarantined. Several successful filtered searches were labelled partial because they could not prove full-board absence. Other partial scans repeatedly fetched the first descriptions and never reached later jobs. Several career boards moved, and Internshala changed its title markup.

Private source snapshots, latest fetch-run evidence, endpoint responses and reproducible scripts are stored under `data/private/source-reliability/`. No credentials or applicant facts are published in this report.

## Read-only public endpoint benchmark

Initial 15-source run used three concurrent collectors, ten pages, twenty description requests and a 90-second limit per source. Results reflect the date of the check; open jobs can change.

| Source | Listed records | Result |
| --- | ---: | --- |
| Kaleris | 16 | Completed query; six Chennai software internships with full descriptions |
| Databricks | 887 | Complete listing; oversized embedded description fallback succeeded |
| Elastic | 401 | Complete listing; no current target internship candidate |
| OpenAI | 821 | Complete bounded public Ashby response; no current target candidate |
| Freshworks | 123 | Complete listing; no current target candidate |
| NVIDIA | 1 | Completed configured India query; current result not retained by personal policy |
| Marvell | 5 | Completed configured query; current results not retained by personal policy |
| Amplitude | 36 | Verified replacement Ashby board completed |
| Observe.AI | 12 | Verified embedded Greenhouse board completed |
| Icertis | 17 | Oracle keyword query completed; not a full-board closure proof |
| PhonePe | 89 | Verified replacement SmartRecruiters board completed |
| AlphaGrep | 15 | Complete listing; one retained candidate with description |
| Zoho | 2 | Public discovery summaries; no proof of a full inventory or full descriptions |
| Microsoft | 100 | Page limit; unfinished query, explicit continuation required |
| Hewlett Packard Enterprise | 40 | Reported total changed during pagination; incomplete, no closures allowed |

Known-role benchmark recovered **Associate Software Engineer Intern, Kaleris, Chennai, R-100658**, plus R-100657, R-100642, R-100646, R-100636 and R-100644. Distinct requisitions remain distinct opportunities.

This first run predates final independent detail cursors, Internshala pagination and the additional ClickHouse/Cerebras mappings. Final regression results, deployment identity and production scan outcomes are recorded below.

## Final local verification

211 backend tests, 13 frontend tests and 16 extension tests pass (240 total). The frontend production build and whitespace check pass. Regression coverage includes sparse generic-intern classification, unchanged description freshness, atomic checkpoint persistence, historical target-scope corrections, preserved owner-paused sources, and superseded sources being excluded from current availability voting. Replaced-only roles need rechecking; they are not declared closed merely because an endpoint moved.

The scheduler now has hourly off-minute trigger opportunities. Source cadence/backoff still bounds actual requests, and operational health reports actual worker gaps and due/stale queues. GitHub scheduled execution remains best effort; this is not a guarantee of continuous exhaustive scanning.

## Follow-up validation — 7 October

The first hosted repair scan revealed a PostgreSQL-specific source-retirement query failure: `DISTINCT` over an opportunity row also compared JSON columns. Listing writes survived, but alias retirement did not. Commit `700d2e5` replaced that query with an identity subquery; a rollback-isolated PostgreSQL integration test now runs in CI. The corrected 36-source run [37651627676](https://github.com/varadharajanv0310/InternshipOS/actions/runs/37651627676) completed with seven full successes, six successful requested scopes, ten partial results and 13 source errors, with **zero worker errors**. A completed workflow does not make its failed source checks successful.

Commit `4953ba9` corrected observed Atlassian and Publicis field schemas, GitHub requisition IDs/native job slugs, and Persistent's nested form pagination. It also protects a worker's saved scan checkpoint when the owner edits source controls. All four configuration patches matched exact old schemas and preserved enabled, verified, priority, cadence and unrelated configuration values. Live run [37653879472](https://github.com/varadharajanv0310/InternshipOS/actions/runs/37653879472) confirmed Atlassian's requested scope, bounded partial Publicis and GitHub coverage, and Persistent's continuing HTTP503 failure. All four outcomes persisted with zero worker errors.

Commit `dca809b` fixes another real Internshala layout: detail pages without JSON-LD were taking a recommended job's URL as the primary job URL. Main-role title, employer, location, native internship ID and description are now isolated from recommendations. Exact final/document canonical URL, employer and available native-ID checks remain enforced. A fresh public Chennai test read 11 listings and enriched seven target descriptions in eight successful requests without errors. Wrong-employer, wrong-ID, wrong-canonical, cross-role redirect and unknown-layout fixtures remain rejected.

Salesforce's official static feed contains 1,517 distinct requisitions with full descriptions and is 9,836,365 decoded bytes. The default 8 MB safeguard rejected it. Only that exact official asset receives a 16 MB ceiling; other configured feeds retain their normal limit and oversized Salesforce payloads are still rejected. A fresh live collector read all 1,517 entries in one request with no errors; **zero entries matched the strict current internship/location policy**, so this total is not advertised as useful internships.

That intermediate code passed 231 local backend checks, with the PostgreSQL integration check skipped locally. Cloud CI [37654957638](https://github.com/varadharajanv0310/InternshipOS/actions/runs/37654957638) passed including that database check, the frontend suite and extension suite: 261 checks overall. Vercel confirmed the existing production alias ready on deployment `internshipos-2a01nefen`. The 48-source verification run included 21 repair sources and 27 overdue previously working sources; its worker failure and the later corrected verification results are recorded below.

The 16:42 UTC intermediate hosted check confirmed authenticated dashboard, analytics, settings, resumes and profile responses, rejection of unauthenticated source access, and automatic submission still off. The registry then had 571 enabled sources: 370 successful, 70 partial, 130 error and one quarantined. **158 historical scope-label corrections remain separate from fresh recovered coverage.** Nine obsolete aliases were superseded only after successful replacement inventory evidence; their history remains available. There were still 416 due and 254 stale sources, despite an on-time heartbeat.

The larger 48-source run persisted 47 source observations but the durable job correctly recorded one worker error: PostgreSQL rejected concurrent overlapping Internshala updates with a deadlock. The failed source's transaction rolled back. The old CLI still exited zero, so the GitHub run alone appeared successful; this discrepancy is recorded rather than counted as a successful worker. Follow-up code adds at most three attempts for server-confirmed aborted PostgreSQL transactions (`40P01` and `40001`), with rollback and a fresh transaction. Ingestion and retirement retry separately so committed observations are not replayed. Ambiguous connection failures and nonretryable errors remain failures, and CLI worker failures now exit nonzero.

Additional direct Workday probes identified an API count contract: HPE returned 107 total with 20 roles at offset zero, then zero total with 20 different roles at offset 20; BrowserStack returned 32/20 then 0/12; Epicor returned 74/20 then 0/20. Repeating offset zero restored the original positive totals. These later-page zero values are sentinels, not inventory loss. The follow-up retains a fresh first-page total while still rejecting contradictory positive totals, repeated pages and early empty pages. Final tests and live checks of the deployed correction are recorded below.

Commit `9416b92` passed cloud CI [37657536132](https://github.com/varadharajanv0310/InternshipOS/actions/runs/37657536132): 271 backend checks including isolated PostgreSQL transaction-abort tests, 13 frontend checks and 16 extension checks. Production is ready on `internshipos-phf6gdre5`. Concurrent production job `7cc1eb9e9fd548ab97a708801b9981f7` checked 16 regional/Workday sources: 14 successful requested scopes, one partial and one source error, with **zero worker errors and one successfully recovered actual PostgreSQL deadlock**. The failed transaction was rolled back; its replay committed one observation batch. A subsequent fresh frontend check completed its discovery scope with full target descriptions and zero worker errors.

Epicor's remaining error led to a separate identity finding: its four public pages contain 74 unique job paths, but `bulletFields[0]` is often a location, not a requisition. The old parser therefore collapsed different jobs sharing locations. The final follow-up uses a verified matching requisition bullet or the full distinct job path as identity, preserving correctly identified existing records. Duplicate posting paths remain distinct; unproven path fallbacks are not relabelled as native requisitions. Historical location-valued identities remain reviewable rather than being destructively rewritten.

## Completed repair batch

Final code revision `afddf2e` is deployed to the existing [InternshipOS](https://internshipos.vercel.app) production project. Vercel confirmed deployment `internshipos-ikv6vvvo4` ready. Final cloud CI [37659340840](https://github.com/varadharajanv0310/InternshipOS/actions/runs/37659340840) passed **276 backend, 13 frontend and 16 extension checks (305 total)**, including all three isolated PostgreSQL checks; the frontend production build passed. Local verification passed 273 checks and skipped only those three database checks.

The final Epicor production check completed its requested scope, with a complete distinct listing inventory and no worker errors. The preceding frontend fresh pass also completed its discovery scope. The 16-source concurrent production check demonstrated a real PostgreSQL deadlock recovery with zero worker errors. A final four-source Workday check (`381daeca377c439f92f99f7f6be8f379`) replaced the remaining count-contract errors with three successful requested scopes and one explicitly unfinished inventory at the page limit, with zero worker errors. The older failed 48-source job remains in the audit history rather than being overwritten as successful.

Authenticated hosted verification at **17:45 UTC on 7 October 2026**:

| Measure | Final observation |
| --- | ---: |
| Enabled sources | 569 |
| Full-board successful statuses | 199 |
| Successful requested query/discovery scopes | 185 |
| Partial statuses | 71 |
| Error statuses | 113 |
| Quarantined statuses | 1 |
| Broken health labels | 97 |
| Blocked health labels | 16 |
| Needs-review health labels | 1 |
| Due sources | 385 |
| Stale sources | 226 |
| Sources waiting for failure backoff | 21 |
| Historical scope-label corrections | 158 |
| Superseded obsolete source aliases | 11 |

Health labels and stored result statuses are different classifications; their error/review counts must not be added together. Successful statuses describe the checked scope and do not establish that all sources are currently fresh. Enabled totals changed from 573 because seven verified replacement routes were added and 11 obsolete aliases were retired after live evidence. Owner-paused sources and preferences were preserved.

All tested authenticated dashboard, analytics, settings, resumes and profile routes return HTTP200; unauthenticated source access returns HTTP401. The technical India internship feed currently has 471 rows using `technical=true`, `kind=internship`, `location=India`, plus the server's stricter Bengaluru/Chennai/remote India policy. This is a filtered record count, not proof of 471 unique, eligible or worthwhile internships: possible duplicates, eligibility unknowns and older records still require review. Kaleris's Chennai requisitions remain present.

The remaining [source-by-source CSV](SOURCE_RELIABILITY_REMAINING.csv) and [priorities report](SOURCE_RELIABILITY_REMAINING.md) identify unsupported public integrations, changed endpoints, access restrictions, unfinished descriptions/pagination and inventory reviews. Scheduling has hourly off-minute opportunities and measured backlog, but GitHub execution remains best effort. No exhaustive or continuous-coverage guarantee is made. AI/Google credentials, project approvals and automatic submission were not changed by this repair.
