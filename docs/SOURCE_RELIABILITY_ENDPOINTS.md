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
