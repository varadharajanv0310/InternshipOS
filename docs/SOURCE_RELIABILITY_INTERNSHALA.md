# Internshala public-source reliability experiment

Two already configured public category pages were read on 6 October 2026 at 7:55–7:58 PM India time, using the existing public HTTP transport. No login, proxy, CAPTCHA solver or access-control workaround was used. Raw responses and metadata are preserved privately under `data/private/source-reliability/`.

## Observed failure

| Configured search | Response | Listing cards | Existing parser output |
| --- | --- | --- | --- |
| Computer science | HTTP 200, 500,986 bytes | 52 | 0 |
| Software development in Chennai | HTTP 200, 306,292 bytes | 11 | 0 |

The Chennai URL containing a space redirected to the employer platform’s canonical hyphenated category URL. Spaces in this configured route were not the observed failure. The pages contained normal visible role cards; a generic CAPTCHA reference in their scripts was not an access challenge.

The shared parser selected `.job-title, .profile, h1`, whereas the actual titles are `h2.job-internship-name > a.job-title-href`. This selector mismatch explains both observed empty parses and is a plausible shared cause of the 17 Internshala errors in the baseline. Only these two categories were tested live; the other categories must be verified after repair.

## Exact safe repairs

1. Add the actual title selectors while retaining older supported markup.
2. Prefer the inner `.company-name` node before falling back to `.company_name`. The latter is a parent container including an “Actively hiring” badge; a combined selector can contaminate employer identity because CSS results follow document order, not selector preference.
3. Preserve explicit location text and correctly normalize the work-from-home marker under the existing India eligibility policy. A non-empty “Work from home” label currently prevents the older URL fallback, losing otherwise relevant remote leads.
4. Read the observed `a.next_page` pagination links. The computer-science first page advertises 14 pages. Accepting page one as a completed search would remain incorrect even after the title fix. Follow public same-host category pagination within budgets, persist a listing cursor and reject repeated pages/links as completion evidence.
5. Keep the scope as discovery. A resumed page segment and a category search are not complete employer inventories and cannot establish closures.

## Evidence and regression fixtures

- `internshala-layout-evidence.json`, `internshala-computer-science-response.html`: first category.
- `internshala-chennai-evidence.json`, `internshala-chennai-response.html`: regional category, including canonical redirect.
- `backend/tests/fixtures/internshala_listing_v2.html`: shortened public card structure plus a synthetic Chennai regression card.
- `backend/tests/test_internshala_layout.py`: title/employer pairing, regional eligibility, next-page handling, bounded continuation, repeated-page rejection and discovery scope.

Provider implementation is owned by the coverage repair agent. The evidence was shared before adapter edits so the fix addresses current public markup rather than inventing selectors from an outdated fixture.

## Repair verification

After the selector and employer isolation repair, both saved real responses parsed successfully: **52 general category records and 11 Chennai records**, compared with zero each before repair. The existing strict target policy retained **14 and seven candidates**, respectively. These retained counts are candidate coverage, not a claim that every listed internship is useful or currently live.

All six new Internshala regression tests passed. The worker persistence-error case also passed in the 19-test health suite: a current heartbeat with `worker_errors > 0` appears failed even without a top-level `status: failed`.

Pagination and cursor continuation retain discovery scope. A stale cursor is reset for a subsequent fresh zero-offset pass; the reset itself is not accepted as a complete inventory.

Reference pages: [computer-science internships](https://internshala.com/internships/computer-science-internship/), [software-development internships in Chennai](https://internshala.com/internships/software-development-internship-in-chennai/).

## Full-description verification

One actual target Chennai listing was fetched at 8:09 PM India time on 6 October: [Full Stack Development at Voicedots Infotech](https://internshala.com/internship/detail/full-stack-development-internship-in-chennai-at-voicedots-infotech1790388263). The public response was HTTP 200, 180,286 bytes, with one JSON-LD JobPosting and a 2,158-character extracted job description. It stated employer identity, Chennai location, technical skills, dates and monthly compensation. This verifies that the public detail endpoint supplies factual enrichment beyond listing titles.

The detail JSON-LD has no `url`, so the requested detail URL supplies its canonical address. Its native identifier differs from the listing URL used as the existing external ID. Enrichment must retain that listing identity, match the exact canonical/final URL and employer, and never create a new source identity from the detail identifier alone. Redirects to another role and employer mismatches are rejected.

Original full responses remain private in `internshala-chennai-detail-response.html` and `internshala-detail-evidence.json`. The committed `internshala_detail_v2.html` fixture uses the observed schema with a shortened synthetic description. `test_internshala_details.py` covers missing JSON-LD URL, immutable listing identity, wrong employer, wrong canonical address, another-role redirect and bounded rotation of target descriptions.

Deliberate listing-only collection (`max_details=0`) is exposed as `description_scope=listing_only` and `description_complete=false`. Production description checks target relevant candidates with a bounded budget; unfinished descriptions remain explicit rather than pretending that listing enumeration supplied full eligibility evidence.

## 7 October: cloud identity failures and resumed pagination repaired

A cloud scan completed without worker persistence errors but reported detail-identity failures across seven Chennai categories. A bounded live reproduction fetched one current software category and its seven target descriptions. Three responses lacked JobPosting JSON-LD. The HTML fallback mixed the primary title/employer/description with the first recommended internship’s link, causing the existing strict URL check to reject a valid primary description.

The fallback now isolates `.detail_view` and its primary `.individual_internship` card. It uses the requested/document canonical address and reads location from the primary card’s `#location_names`; recommended links, employers and descriptions cannot rebind the role. When both listing and main-detail DOM internship IDs are present, they must also match. Canonical-URL, employer and redirected-role checks remain strict. Diagnostics identify the failed component and public job URL.

Live verification after repair: **11 software-category listings, seven target descriptions, eight HTTP 200 requests, 5.293 seconds, no collection error**, with complete target-description coverage. Private evidence: `internshala-identity-evidence-2026-10-07.json`, three mismatched HTML responses, and `internshala-identity-verified-2026-10-07.json`.

The frontend category had a separate saved checkpoint at page two. Page one yielded 40 cards; page two yielded none despite a stale SEO heading of 54. Its public HTML explicitly contained both a hidden `#isLastPage` value of 1 and the regional `#individual_location_end_result` end-of-results container. The public search script’s ordinary unauthenticated GET pagination route independently returned `currentPageCount=0` and `is_last_page=true`. No cookies, tokens or challenge solving were used; the production adapter does not depend on this additional AJAX request.

Only those paired explicit HTML markers establish an empty terminal location page. A resumed terminal checkpoint preserves current head leads, resets its cursor to zero and still requires a fresh pass before claiming query completeness. Unknown empty markup retains an explicit pagination failure and also recovers head leads rather than trapping the source at a blank checkpoint. A last-page flag alone is insufficient.

Live frontend verification: starting at saved cursor one retained **40 head listings**, reported incomplete inventory and reset to zero; the subsequent fresh zero-offset scan enumerated **40 listings**, ended with no error and retained discovery scope. Each required three public requests and roughly three seconds. These particular probes intentionally skipped descriptions and explicitly reported listing-only coverage. Evidence: `internshala-frontend-cursor-verified-2026-10-07.json` and the HTML/script/API evidence beside it.

All **61** focused Internshala and shared coverage regression tests passed after these repairs. New cases cover main-card scoping, native DOM-ID mismatch, conflicting document/schema canonical addresses, unsupported layouts, checkpoint recovery and explicit empty-terminal proof. Discovery completeness still cannot establish employer-wide vacancy closure.
