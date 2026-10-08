# Remaining source reliability work

Snapshot captured: 2026-10-08T16:23:55Z. Generated from saved read-only evidence.

**564 enabled sources: 431 successful, 47 partial, 85 error and 1 quarantined.** The accompanying [CSV](SOURCE_RELIABILITY_REMAINING.csv) lists 133 enabled unsuccessful sources, including any explicit review/blocked/broken health state.

## Before and after: label corrections are separate from recoveries

The original baseline had 573 enabled sources: 183 complete, 157 error, 224 partial, 9 quarantined.
The system records **158 historical requested-scope label corrections**. These retained their original check times and must not be presented as newly recovered feeds.
**27 superseded aliases** retain their history and replacement references. Their retirement is separate from recovery and excludes them from the enabled-source total.
Comparing stable source IDs and board-check timestamps, 234 originally unsuccessful sources are now successful with a later check; 0 became successful without a later board check; and 17 newly registered sources are currently successful. The first figure is an observed status transition after a fresh check, not proof that every transition required an endpoint repair.
Historical label corrections and later checks can overlap: a previously relabeled source may subsequently be checked again. These measures describe different events and must not be added together as a recovery count.
Since the comparison snapshot captured at 2026-10-07T16:20:49.293446+00:00, 55 previously unsuccessful sources have a successful check after that capture time. Superseded or disabled aliases are excluded from enabled totals and are not counted as recovered connections. Other scheduled checks ran during this period; these transitions are not attributable solely to the new code.

## Remaining priorities

1. Verify official public integrations for career pages that lack a supported inventory feed. Prioritize employers offering Bengaluru, Chennai or India-accessible remote internships; retain evidence and source identity.
2. Continue bounded inventory and description segments using their saved positions. State Street and FIS passed their live target-scope reads; Accenture remains time-limited. LinkedIn searches remain bounded discovery and missing-employer cards cannot establish identity.
3. Monitor actual scheduler timing and capacity after the backlog catch-up. Budget-only scans with cursors can resume after 30 minutes; failed sources retain backoff. Historical identity corrections, mirror reconciliation and current availability are recorded separately in PROJECT_AND_SHORTLIST_REVIEW_2026-10-08.md; preserve real hiring-employer and subsidiary scope.
4. Continue other unfinished inventories and full-description segments. Preserve saved cursors and bounded requests; an incomplete scan must not close existing vacancies or turn summary descriptions into full evidence.
5. Replace obsolete or restricted endpoints only when an employer-linked alternative is verified. Keep access restrictions explicit and preserve history; do not disable failures to improve headline counts.

| Remaining cause | Sources |
|---|---:|
| Public integration needed | 57 |
| Inventory and details unfinished | 41 |
| Endpoint obsolete | 12 |
| Access restriction | 10 |
| Details unfinished | 4 |
| Inventory unfinished | 3 |
| Employer identity review | 2 |
| URL or DNS | 1 |
| Upstream unavailable | 1 |
| Request schema | 1 |
| Response limit | 1 |

Collector schedule status: `on_time`. Due sources: **12**; stale: **16**; awaiting retry: **27**.

Counts use saved board health, not the legacy per-read status, which can change after an individual posting refresh. Full-board success, target-query success, description completeness and personal eligibility remain different claims. All endpoint response totals refer to public records and are not useful-internship counts. No engine can establish that it finds every useful internship across unsupported, blocked or unpublished sources.

Public outputs contain no account credentials, configuration bodies, cookies, raw errors or personal profile facts. Query parameters in source URLs are limited to a small public search allowlist. Detailed snapshots and the rerunnable report generator remain private under `data/private/source-reliability/`.
