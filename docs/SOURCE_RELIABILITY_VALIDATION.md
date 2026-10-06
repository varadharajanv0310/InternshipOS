# Source reliability validation — 6 October 2026

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

This first run predates final independent detail cursors, Internshala pagination and the additional ClickHouse/Cerebras mappings. Final regression results, deployment identity and production scan outcomes will be appended after verification.

## Final local verification

211 backend tests, 13 frontend tests and 16 extension tests pass (240 total). The frontend production build and whitespace check pass. Regression coverage includes sparse generic-intern classification, unchanged description freshness, atomic checkpoint persistence, historical target-scope corrections, preserved owner-paused sources, and superseded sources being excluded from current availability voting. Replaced-only roles need rechecking; they are not declared closed merely because an endpoint moved.

The scheduler now has hourly off-minute trigger opportunities. Source cadence/backoff still bounds actual requests, and operational health reports actual worker gaps and due/stale queues. GitHub scheduled execution remains best effort; this is not a guarantee of continuous exhaustive scanning.
