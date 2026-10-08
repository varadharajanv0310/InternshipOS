# Remaining source reliability work

Snapshot captured: 2026-10-07T17:45:30.577032+00:00. Generated from saved read-only evidence.

**569 enabled sources: 384 successful, 71 partial, 113 error and 1 quarantined.** The accompanying [CSV](SOURCE_RELIABILITY_REMAINING.csv) lists 185 enabled unsuccessful sources, including any explicit review/blocked/broken health state.

## Before and after: label corrections are separate from recoveries

The original baseline had 573 enabled sources: 183 complete, 157 error, 224 partial, 9 quarantined.
The system records **158 historical requested-scope label corrections**. These retained their original check times and must not be presented as newly recovered feeds.
**11 superseded aliases** retain their history and replacement references. Their retirement is separate from recovery and excludes them from the enabled-source total.
Comparing stable source IDs and board-check timestamps, 81 originally unsuccessful sources are now successful with a later check; 113 became successful without a later board check; and 7 newly registered sources are currently successful. The first figure is an observed status transition after a fresh check, not proof that every transition required an endpoint repair.
Historical label corrections and later checks can overlap: a previously relabeled source may subsequently be checked again. These measures describe different events and must not be added together as a recovery count.
Since the 7 October resumed snapshot, 9 previously unsuccessful sources have a successful check after that snapshot's capture time. Superseded or disabled aliases are excluded from enabled totals and are not counted as recovered connections.

## Remaining priorities

1. Verify official public integrations for career pages that lack a supported inventory feed. Prioritize employers offering Bengaluru, Chennai or India-accessible remote internships; retain evidence and source identity.
2. Continue the bounded Publicis and GitHub listing scans from their saved positions. Atlassian's guarded mapping has passed fresh validation; Persistent still returns HTTP503 and needs a successful upstream retry before recovery can be claimed.
3. Reduce stale coverage and retry backlog with measured scheduling capacity, prioritization and backoff. Review historical location-valued Workday IDs without destructive merging; preserve real hiring-employer and subsidiary scope.
4. Continue other unfinished inventories and full-description segments. Preserve saved cursors and bounded requests; an incomplete scan must not close existing vacancies or turn summary descriptions into full evidence.
5. Replace obsolete or restricted endpoints only when an employer-linked alternative is verified. Keep access restrictions explicit and preserve history; do not disable failures to improve headline counts.

| Remaining cause | Sources |
|---|---:|
| Public integration needed | 66 |
| Inventory and details unfinished | 61 |
| Access restriction | 16 |
| Endpoint obsolete | 15 |
| Inventory unfinished | 11 |
| Timeout | 8 |
| URL or DNS | 2 |
| Request schema | 2 |
| Employer identity review | 1 |
| Details unavailable | 1 |
| Upstream unavailable | 1 |
| Response limit | 1 |

Collector schedule status: `on_time`. Due sources: **385**; stale: **226**; awaiting retry: **21**.

All endpoint response totals refer to public records and are not useful-internship counts. Full-board success, target-query success, description completeness and personal eligibility remain different claims. No engine can establish that it finds every useful internship across unsupported, blocked or unpublished sources.

Public outputs contain no account credentials, configuration bodies, cookies, raw errors or personal profile facts. Query parameters in source URLs are limited to a small public search allowlist. Detailed snapshots and the rerunnable report generator remain private under `data/private/source-reliability/`.
