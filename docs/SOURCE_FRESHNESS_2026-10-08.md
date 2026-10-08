# Source freshness — 8 October 2026

## Diagnosis

- The hourly workflow capped each run at 96 sources. The previous snapshot had 385 due sources; fast boards could not use the spare time after this fixed count.
- The worker used an in-process mutex, which did not exclude a separate scheduled or local worker. Durable job claims protected one queue item, but default unqueued collection could still overlap.
- Freshness remains based on actual board observations. Saved-role detail reads cannot advance the inventory clock, and backoff does not conceal staleness.
- The coordinating agent's live baseline at 06:30 UTC (12:00 pm IST) on 8 October showed 235 due and 124 stale sources. Recent scheduled completions had gaps of roughly 4–6 hours despite the hourly schedule.

## Implemented

- Increase the hourly selection ceiling to 384 sources while retaining six concurrent requests and a bounded 26-minute collection window. Do not begin another source unless its configured network timeout and persistence reserve fit.
- Persist collected observations before stopping. Unstarted sources remain due; explicit queued source lists retain their unfinished IDs for continuation.
- Add a database-backed expiring worker lease and token-checked completion/release, without resetting source cadence or owner preferences.
- Register queue and worker-lease models explicitly in standalone database initialization, so clean scheduled bootstrap creates both tables before the worker starts.
- Prefer verified working and India-scoped sources, with bounded preference and a reserved oldest-due lane so broken or long-tail sources are not silently starved.
- Resume purely budget-limited scans with a saved cursor after 30 minutes (or the owner's shorter cadence). Keep the owner's full-board cadence and real error backoff unchanged; an unproved inventory without a cursor does not create a fast retry loop.
- Limit public LinkedIn searches to two per collection wave while filling spare slots with unrelated feeds. The shared request pace otherwise caused two source timeouts in the first concurrent production check.
- Expose overdue lag, measured completed-board throughput, pending work, capacity assumptions and lease state. An hourly trigger alone is never a claim of 24/7 reliability.
- Add a second off-minute trigger at minute 47, alongside minute 17. This gives delayed scheduler events another chance without forcing requests on sources whose cadence or backoff is not due.
- Show due and stale counts separately for successful, partial and failing sources. A failure retry backlog must not be presented as stale working coverage.
- Preserve the last inventory-collection metrics independently of targeted role rechecks. A recent role refresh cannot make an older collection run appear timely or erase its measured throughput.
- Add a durable `refresh_opportunity` request resolved only from stored enabled, verified, same-employer appearances. It reads at most three sources, checks exact native identity or canonical URL/employer evidence, and keeps board clocks and continuation cursors intact. Failed detail reads leave the appearance's listing/detail timestamps unchanged and never prove closure.

The collection budget governs when new waves start, with a source-timeout plus 30-second persistence reserve. Started observations finish persistence before stopping; no cancellation discards collected evidence. A slow database may extend final persistence beyond the launch budget. The 384-source ceiling is capacity, not a guarantee of successful scans. The due date/cadence/backoff settings themselves are preserved.

## Validation

Focused scheduler, ingestion, persistence, source-health and targeted recheck checks: **103 passed, 3 skipped locally**. The three skipped checks require isolated PostgreSQL; they include the new concurrent lease test and existing transaction-abort retry checks. They do not target hosted data.

Meaningful checks cover long-tail service despite recurring preferred boards, paused/backoff preservation, simultaneous first lease claims, expired-owner release protection, exact queued continuation, lost-lease refusal, budget cuts retaining observations, empty explicit lists, native ID/request URL/employer mismatch refusal, and board clock preservation after successful and failed role rechecks.

An additional isolated subprocess starts with no worker module imported, initializes a fresh temporary SQLite database, verifies `background_jobs` and `collection_worker_leases`, and repeats initialization to prove idempotence. The scheduler, health, persistence and targeted-recheck suite passes **59 checks with 3 PostgreSQL-only skips** after this addition.

Production backlog verification will be recorded by the coordinating agent after deployment. Scheduled triggers remain best effort; the report exposes the actual delay rather than claiming continuous guaranteed operation.
