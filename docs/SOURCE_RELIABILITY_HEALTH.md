# Source reliability: health, freshness and scheduled collection

Checked on 6 October 2026. This document records source monitoring repairs and read-only scheduler evidence. Model selection, Google integration and application submission are outside this change.

## Findings

1. The old stale threshold was `max(24, cadence_hours * 2)`. A source on a six-hour cadence could go almost a day without a warning. Stale now means more than twice its stated cadence; a missed due date is visible immediately as **Due**, before it becomes stale.
2. `last_checked`, `last_success`, status and failure counters also changed after refreshing saved-role descriptions. Those targeted requests are not a board inventory. The API and worker now use `config.board_checked_at` and the separate `config.board_health` snapshot for board timing and health. Historical sources fall back conservatively until their next board observation.
3. A `partial` status took precedence over transport errors. Mixed errors such as `detail_limit_reached; HTTP 403` could be presented merely as Partial. Access restrictions and request failures now retain their actionable diagnoses.
4. Listing completeness, description completeness and full-inventory closure evidence are different. A listing scan with unfinished descriptions remains explicit; a complete regional query is **Successful (target scope)** and does not imply that the full employer inventory was checked.
5. Failure backoff postpones retries but cannot make an old inventory appear fresh. The UI shows both stale coverage and the permitted retry date.

## Health contract

`source_health.health(source, now=None)` returns the following, encoded to JSON by the existing serializer:

| Field | Meaning |
| --- | --- |
| `label` | Successful, Successful (target scope), Partial, Blocked, Broken, Needs review, Not checked or Unverified |
| `board_checked_at` | Most recent non-targeted board attempt |
| `last_success` | Most recent successful board observation, not a later saved-description read |
| `inventory_complete` / `description_complete` | Explicit listing/description completeness when recorded; otherwise unknown |
| `full_inventory` | Full inventory accepted for absence/closure evidence |
| `coverage_scope` | Full, query, discovery or unknown |
| `cadence_due_at` | Last board check plus configured source cadence |
| `next_due_at` | Last board check plus the larger of cadence and failure backoff |
| `due` / `overdue_hours` | Whether an enabled source can be checked now, and its delay beyond that date |
| `stale` / `freshness` | Old coverage, due coverage, fresh coverage, paused state, missing checks or clock issues |
| `backoff` / `retry_hours` | A source is waiting for its retry window; failures are not hidden |
| `issue_code` / `action` | Specific problem category and suggested repair |

Internal timestamp values are UTC datetimes. `serialize.json_value` produces ISO dates for the API. Worker selection reuses `timing`, preventing disagreement between the displayed and executed retry schedule. Disabled sources are neither due nor stale; pausing them does not count as repaired coverage.

Issue categories include rate limiting, access blocks, changed addresses, temporary network failures, inventory review, response limits, parser/query scope and unfinished bounded scans. Pure budget exhaustion is a partial scan. Mixed budget and request failures are not downgraded to partial-only warnings.

`collection_health.collection_health(db)` exposes actual worker completion, a target interval, a delayed/failed/not-reported state, enabled-source counts, due/stale backlog, sources waiting for retry and health counts. It performs no external requests and grants no scheduler credentials to the hosted API. Source health shows these values and the last board attempt, last success and next allowed check.

## Scheduler investigation

The existing workflow was active on the default repository and configured for `17 */2 * * *` UTC. All 12 most recent scheduled runs in the inspected history completed successfully. They did not arrive every two hours:

| Scheduled run | Created / started, India time | Gap from prior scheduled creation |
| --- | --- | --- |
| 37423922205 | 6 October, 11:58:26 AM | 7 hours 45 minutes 28 seconds |
| 37384208166 | 6 October, 4:12:58 AM | 7 hours 51 minutes 51 seconds |
| 37328059269 | 5 October, 8:21:07 PM | 9 hours 1 minute 51 seconds |
| 37269470016 | 5 October, 11:19:16 AM | 6 hours 34 minutes 25 seconds |

For run 37423922205, the job started two seconds after workflow creation and finished at 12:06:53 PM India time, taking eight minutes 25 seconds. This measured run does not support blaming a long collector execution or a concurrency backlog for the preceding eight-hour gap. The workflow history does not identify the upstream cause of every missing expected trigger.

GitHub documents that scheduled events can be delayed under load and queued jobs may be dropped. Scheduling away from the hour reduces a known risk, but the existing minute 17 already did that. See [GitHub scheduled workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

The minimal free improvement is an hourly off-minute trigger with the existing bounded worker and per-source due checks. More trigger opportunities help recover late delivery; this remains a best-effort schedule, not a two-hour guarantee. Do not create a self-dispatch loop or grant the app broad GitHub write access. A stronger guarantee would require a separately evaluated scheduler/worker; no paid or external persistent service was added during this investigation.

Operational checks must use measured worker completions and source timestamps. A successful workflow or a recent worker heartbeat alone does not establish that every due source was scanned.

## Evidence and verification

- Private source snapshot: `data/private/source-reliability/baseline-sources.json` and `baseline-summary.json`.
- Private fetch evidence: `data/private/source-reliability/baseline-failure-details.json`.
- Read-only workflow history: `data/private/source-reliability/schedule-history-2026-10-06.json`.
- Source code: `backend/internshipos/source_health.py`, `collection_health.py`, and the source-health section of `frontend/src/Settings.tsx`.
- Regression tests: `backend/tests/test_collection_health.py` cover fast and slow cadences, targeted-read isolation, mixed failures, retry backoff, paused sources, scoped completion, invalid clocks and worker gaps.
- Frontend production build passed. Focused health tests passed; the main agent performs integrated tests and hosted verification after combining provider and worker repairs.

These changes preserve failure evidence. They do not erase failing sources or count disabled boards as repaired.
