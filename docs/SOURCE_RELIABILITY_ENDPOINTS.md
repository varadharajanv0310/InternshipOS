# Source reliability: endpoint and employer mapping audit

Updated 2026-10-06. This audit preserves broken and partial statuses until a real successful check establishes the result; an unavailable feed is never converted into a zero-job result.

## Findings in progress

- Public ATS URL discovery currently assumes the first URL path segment is the employer's board slug. That is incorrect for Lever public API URLs (`/v0/postings/{site}`), Ashby public posting URLs (`/posting-api/job-board/{board}`), and SmartRecruiters public API URLs (`/v1/companies/{company}/postings`). An official careers page linking one of those endpoints can therefore create a permanently broken source.
- Greenhouse embedded boards identify the employer through the `for` query parameter. Treating `embed` as a company slug creates a false board mapping. Discovery must normalize these links to the actual board token and preserve the EU region.
- Discovery should record an official careers-page redirect to a supported ATS as binding evidence. A supplied ATS URL alone remains a candidate, as before.
- Fresh baseline confirms 573 enabled sources: 157 errors, 224 partial, 183 complete and nine quarantined. Generic pages account for 108 errors; they are often marketing pages with JavaScript integrations that the JSON-LD reader cannot inventory.
- A failed generic marketing page can coexist with a working structured source for the same employer. Freshworks and BrowserStack both already have structured inventory sources. Repairing or transparently linking the redundant alias must preserve the evidence rather than claim the employer was previously uncovered.

## Primary technical references

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)
- [Lever public postings API](https://github.com/lever/postings-api)
- [Ashby public job posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)

## Verified employer mappings

All endpoint checks were read-only, without account cookies or tokens. The counts below are all public jobs in the endpoint result, not useful internship counts. Profile and location rules are applied after collection.

| Employer | Previous problem | Evidence-backed replacement | Live observation |
|---|---|---|---|
| PhonePe | Two old Greenhouse endpoints return 404 | SmartRecruiters `PHONEPELIMITED` | Official careers page's JavaScript fetches [PhonePe's public feed](https://www.phonepe.com/apollo/job-postings/latest.json). Published records point to [PhonePe's SmartRecruiters board](https://careers.smartrecruiters.com/PHONEPELIMITED). The structured API reports 89 public jobs. Unpublished first-party rows are excluded. |
| AlphaGrep | `/careers` returns 404 | Greenhouse `alphagrepsecurities` | The [current official `/career/` page](https://www.alpha-grep.com/career/) loads an [official integration script](https://www.alpha-grep.com/assets/greenhouse-legacy.js), which reads the [first-party jobs proxy](https://www.alpha-grep.com/api/greenhouse-jobs.php). Its explicit Greenhouse URLs match the live 15-job public ATS feed. |
| Amplitude | Greenhouse board returns 404 | Ashby `amplitude` | [Official careers page](https://amplitude.com/careers) directly links [Ashby](https://jobs.ashbyhq.com/amplitude). API returns 36 public jobs. |
| ClickHouse | Greenhouse board returns 404 | Ashby `clickhouse` | [Official careers page](https://clickhouse.com/company/careers) references a [first-party integration chunk](https://clickhouse.com/_next/static/immutable/chunks/2rry_oep3kltq.js) explicitly fetching the live Ashby posting API. API returns 195 public jobs. |
| Cerebras Systems | Greenhouse board returns 404 | Ashby `cerebras` | [Official careers page](https://www.cerebras.ai/join-us) links [Open Positions](https://www.cerebras.ai/open-positions), which embeds explicit Ashby application links including Bengaluru roles. API returns 117 public jobs. |
| Observe.AI | Marketing page has no JSON-LD inventory | Greenhouse `observeai` | [Official careers page](https://www.observe.ai/careers) embeds Greenhouse's documented job-board script with this token. API returns 12 public jobs. |
| Icertis | Marketing page has no JSON-LD inventory | Oracle `iaaviz`, site `Jobs-at-Icertis` | [Official careers page](https://www.icertis.com/company/careers/) directly links the [Oracle board](https://iaaviz.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Jobs-at-Icertis/). Public requisition finder responds successfully. Internship keyword coverage remains a query, not full-board proof. |
| Zoho | Marketing page has no JSON-LD inventory | Explicit first-party public Recruit API | [Official careers page](https://www.zoho.com/careers/) includes a [public integration script](https://www.zohowebstatic.com/sites/zweb/js/translation/zoho_general_pages/29220.js) declaring the India careers API. It returns two public rows with summary descriptions; discovery scope and incomplete detail remain explicit. |
| Freshworks | Redundant generic marketing-page error | Existing SmartRecruiters `Freshworks` | Official careers page directly links the existing canonical board. API reports 123 jobs. No new employer coverage should be attributed to removing a duplicate alias. |
| BrowserStack | Redundant generic marketing-page error | Existing Workday `browserstack/External` | Official careers page directly links the existing canonical Workday board. A public internship keyword request returns 15 matches; relevance is evaluated individually. |

The idempotent repair manifest is [source_endpoint_repairs.json](../backend/internshipos/data/source_endpoint_repairs.json). It matches employer, old provider and old URL explicitly and preserves owner settings and historical source appearances. Successful health must come from a real collection result after repair.

## Discovery changes and tests

- Correct employer-token extraction for Lever, Ashby, SmartRecruiters public API links and embedded Greenhouse boards; reject private API paths and missing/malformed board tokens.
- Preserve regional board hosts while normalizing URLs. Reject credential-bearing and lookalike vendor URLs.
- Prefer a supplied official careers page over the marketing homepage, and record official careers redirects to supported ATS boards as binding evidence.
- Recognize Greenhouse's documented embedded board script without executing JavaScript or treating arbitrary script claims as trusted employer bindings.
- Follow a bounded official careers-to-openings chain, including separately named `open-positions` pages. The four-page limit and public-URL validation remain enforced.
- Local verification: **65 tests passed**, covering the 20 new discovery regression cases plus the existing ingestion tests. Unknown employer identity and supplied-only ATS URLs still remain candidates.

## Unresolved cases

- The initially unverified ClickHouse and Cerebras candidates were subsequently bound through their current official integrations and promoted into the repair manifest. A responding guessed slug alone was insufficient.
- Postman's old board and two alternative guessed board URLs return 404. The current official careers page requires additional custom-integration inspection. No invented replacement was added.
- Whatfix's official page points to a public Trakstar board through a Recruiterbox redirect. It is a legitimate lead but needs a supported, tested parser before inventory claims.
- Access challenges for Tower Research and Coinbase remained explicit failures; no anti-bot or CAPTCHA bypass was attempted.

Raw responses, SHA-256 fingerprints, bounded probe scripts and source-level baseline are persisted privately in `data/private/source-reliability/`. They contain no account credentials. The repair manifest and this report contain only public endpoint evidence.

## Hosted follow-up audit — 7 October 2026

Read-only hosted snapshot checked at 16:20 UTC: 579 enabled sources, comprising 198 complete, 177 complete for the requested scope, 68 partial, 135 errors and one quarantined source. Errors include 119 broken connections and 16 access restrictions. The 158 historical scope-label corrections preserve their previous check times and do not represent new successful network checks.

The collection service was on schedule, but 423 sources were due, 255 stale and 28 awaiting a retry. This backlog needs collection capacity and prioritization review; an on-time scheduled run alone does not prove fresh coverage of every source.

| Employer | Verified failure | Guarded correction | Public observation |
|---|---|---|---|
| Atlassian | An array used as a description field fails the declared field grammar. | Join overview, responsibilities and qualifications through the supported safe concat specification; retain role ID and type. | [Public feed](https://www.atlassian.com/endpoint/careers/listings) responds HTTP200 with 348 records and all declared fields. |
| Publicis Groupe | Nested records have no declared title/fields mapping. | Map fields inside `data`, keep existing canonical URL extraction, and use `full_location` so multiple cities remain visible. | [Public API](https://careers.publicisgroupe.com/api/jobs?page=1&limit=2) responds HTTP200 and reports 3,047 public jobs. Example `full_location` includes both Melbourne and Sydney. This count is not a claim that the bounded collector read all pages. |
| GitHub | The adapter replaced the native slug with an empty derived value, collapsing distinct role URLs; no stable ID was declared. | Preserve native slug unless derivation is explicitly declared, use `req_id`, and declare the observed default page size of ten. | [Public API](https://www.github.careers/api/jobs?page=2) responds HTTP200, reports 71 jobs, and returns distinct IDs on pages one and two. The corrected adapter has 37 passing coverage regression tests. |
| Persistent Systems | The paging parameter is inside JSON encoded in the `filterCri` form field, but the old declaration updated a separate top-level field. | Update `filterCri.paginationStartNo` using the supported nested form grammar. | The existing public search endpoint currently responds HTTP503. This is a request-grammar correction only; its health stays failed until a fresh successful inventory check. |

All four `config_repairs` require the exact existing employer, provider, URL, API endpoint and broken configuration values. They preserve source identity and owner settings. Local validation confirms every expected configuration matches the fresh hosted snapshot and every new field uses the safe extraction grammar. The endpoint migration observation date remains unchanged to preserve existing migration identities.

The largest remaining failure groups are 71 generic pages without public JobPosting data, 20 HTTP404 responses, 16 HTTP403 responses and eight JobSpy timeouts. These require additional supported employer integrations, verified endpoint replacements or honest access-restriction handling. They must not be counted as successful merely by hiding or disabling failures.

Private evidence: `resumed-2026-10-07-sources.json`, `resumed-2026-10-07-summary.json` and `resumed-2026-10-07-public-mapping-probes.json` under `data/private/source-reliability/`. The read-only audit also confirms unauthorized source access returns HTTP401 and automatic application submission remains off.

## Canonical-route and subsidiary scope review — 7 October 2026

- [Mastercard's official careers page](https://careers.mastercard.com/) explicitly links `https://mastercard.wd1.myworkdayjobs.com/CorporateCareers`, matching an existing successful target-scope Workday source. This is a concrete canonical-binding candidate for the failing generic route; retire an alias only through the established evidence and live-result checks.
- [State Street's official careers page](https://careers.statestreet.com/) links `https://statestreet.wd1.myworkdayjobs.com/en-US/Global/introduceYourself`. This verifies the tenant/site but is a talent-network link, so it is weaker proof that the generic job-search route and existing Workday inventory are interchangeable.
- BrowserStack, Freshworks, Icertis and Observe.AI already have stronger official bindings recorded above. Shared company identity alone does not establish route equivalence.
- Intelerad is a valid GE HealthCare subsidiary: GE HealthCare [completed the acquisition on 18 March 2026](https://www.gehealthcare.com/en-us/about/newsroom/press-releases/ge-healthcare-completes-intelerad-acquisition-accelerating-shift-to-cloud-first-enterprise-solutions-to-deliver-precision-care). Its successful SmartRecruiters inventory represents Intelerad's hiring scope and must not be presented as complete coverage of every GE HealthCare business or country.
- Sensorfact is a valid ABB subsidiary: ABB's [Q1 2026 financial information](https://library.e.abb.com/public/92757491d9cc40af8425ef03a7f45f81/ABB-Q1-2026-financial-information.pdf), page 13, records acquisition of all shares on 3 February 2025. Its Ashby board is a distinct hiring scope from ABB's main Workday board and BrightLoop's careers route. Preserve actual hiring-employer labels and scope rather than quarantining valid subsidiaries or merging them into full-parent coverage.

The remaining-source CSV and priorities report are generated from saved source-level snapshots. Counts of historical label corrections, fresh successful checks, new sources and disabled/superseded aliases remain separate. Public outputs exclude raw configurations, secrets, private profile data and unsanitized error strings.

## Workday later-page total contract — 7 October 2026

Bounded read-only requests to three official boards confirmed a paging-contract mismatch. With identical final query and facets, page zero supplies a positive authoritative count, later offsets supply `total: 0` while returning distinct job records, and a repeated page-zero request restores the same positive count:

| Public board | Offset zero: total / rows | Offset twenty: total / rows | Repeated offset zero: total / rows |
|---|---:|---:|---:|
| HPE, `Jobsathpe` | 107 / 20 | 0 / 20 | 107 / 20 |
| BrowserStack, `External` | 32 / 20 | 0 / 12 | 32 / 20 |
| Epicor, `epicorjobs` | 74 / 20 | 0 / 20 | 74 / 20 |

The previous adapter interpreted the later zero as a changing live inventory, overwrote its positive count, and stopped the scan early. This was a collector error for the observed contract, not evidence that those employers' inventories were unstable.

The corrected Workday segment keeps its fresh zero-offset count. It accepts a later zero only at a nonzero offset when that head count is positive and the page contains entirely valid, distinct new jobs. Contradictory positive totals, early empty pages, repeated/missing records, malformed counts and records exceeding the head count remain incomplete. A resumed segment obtains a fresh head using its final query/facets; it still cannot establish full absence from a continuation segment. The 2,000-job partitioning guard and listing/detail request bounds remain enforced.

Targeted verification: **102 tests passed**, comprising 18 new Workday contract cases and the existing ingestion/coverage suites. Live recovery requires a fresh collection after deployment; existing error labels are not rewritten merely because the code changed. The public counts above are listing counts, not personalized internship counts or full-description claims.

The reproducible bounded probe and exact public request bodies, IDs, response fields and timings are saved privately as `probe_workday_total_contract.py` and `workday-total-contract-2026-10-07.json`. Request bodies are captured independently so later facet selection cannot alter the recorded discovery request.

## Epicor Workday identity contract — 7 October 2026

Four same-query public pages from Epicor's official Workday board returned **74 rows with 74 unique `externalPath` values**. The page sizes were 20, 20, 20 and 14. There were no duplicate paths. However, the old parser observed only 32 unique IDs because Epicor's `bulletFields` begins with a location, such as `["India, Bangalore", "JR105458"]`. Treating the first bullet as an ID merged different requisitions in the same city and incorrectly reported repeated pages.

The corrected parser accepts a bullet as a requisition ID only when it matches the posting path's exact terminal ID. Otherwise the full public posting path supplies unique listing identity. A duplicate-post path such as `_JR1-1` retains its own path identity while the explicitly supplied `JR1` may remain its common requisition ID; it is not collapsed into the normal `_JR1` listing. Existing normal IDs remain unchanged. Unproven location or administrative bullets are never presented as requisition IDs.

Target detail lookup now recognizes all bullet positions and path fallbacks, so a correctly identified role is still eligible for description refresh. **107 targeted tests passed**, including five additional identity cases alongside the 18 paging-contract cases. This is a code-level repair; a new hosted collection must confirm actual recovery.

Historical location-valued source IDs are not trustworthy requisition identities. Preserve their appearances and audit history for review; do not destructively merge or rewrite old opportunities merely to align them with new IDs. The public response capture is saved privately in `epicor-four-page-contract-2026-10-07.json` with exact bodies and all observed identities.
