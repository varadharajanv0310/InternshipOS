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
