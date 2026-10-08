# Native feed repairs — 8 October

Two new readers are implemented and their eight contract tests pass. Production collection finished at **16:17 UTC**. Publishing the permanent readers to the existing worker and hosted application is in progress.

| Employer | Previous gap | Verified public contract | Scope |
|---|---|---|---|
| Groq | Generic career-page reader could not parse the board | Gem's documented unauthenticated `GET /job_board/v0/groq/job_posts/` returned 33 postings with native IDs, full descriptions and dates | Full unfiltered board, with identity and schema guards |
| MoEngage | Generic reader could not parse native Trakstar cards/details | The employer-linked Trakstar board returned 25 native cards; the first detail returned a full JD in `.jobdesciption` | Page discovery; cannot close other postings |

These are source recoveries, not 58 useful internships. **Both boards had zero qualifying technical internship candidates at this check.** Groq's full-board inventory succeeded; its previously unverified employer binding remains unverified. MoEngage's native page discovery succeeded and its old generic route was retired after the replacement's observation was persisted. MoEngage is scoped success, not full-board completeness. The Bengaluru/Chennai/India-remote policy still applies.

At **16:23 UTC**, owner API board health showed **564 enabled sources: 431 successful (213 full and 218 scoped), 47 partial, 75 broken, 10 blocked and one needing review**. No successful source was overdue or stale; 12 partial sources were due, 16 failing sources were stale and 27 awaited retry. The worker was on time and idle after finishing its run. These are timestamped observations, not guarantees.

The 12 obsolete endpoints remain unresolved. Postman's current official careers page does not declare a usable native feed in the fetched page; HubSpot's current page and declared script still refer to the failed Greenhouse board; Coinbase's official page denied the read. No guessed tenant or empty page was registered as a successful replacement.

Gem source contract: [official API reference](https://api.gem.com/job_board/v0/reference), [Gem's Job Board API guide](https://help.gem.com/databases/gem-help-center/the-job-board-api). MoEngage binding: [official careers](https://www.moengage.com/careers/), [native board](https://moengage.hire.trakstar.com/).

Tests cover foreign board identity, duplicate native IDs, missing descriptions, changed schema, mismatched detail titles, exhausted detail budgets and error pages. Application forms are excluded from descriptions. No application-submission endpoints are used.

Saved private experiment: `data/private/remaining-items-2026-10-08/public-contract-probes.json`, source response bodies, and before-images. Google and AI credentials remain absent: the user confirmed neither has been created.
