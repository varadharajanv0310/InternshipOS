# InternshipOS database transfer outage — 17 November 2026 (IST)

The hosted dashboard could not load because Neon blocked connections to the existing production database. The project used its **5 GB monthly public network transfer allowance**. Neon's 80% alert arrived 9 November; the 100% alert arrived 11 November. A previous 100% alert arrived 17 October.

Evidence: live `/api/health` returned HTTP 500 while a protected endpoint still returned HTTP 401 without a session. The [collector run](https://github.com/varadharajanv0310/InternshipOS/actions/runs/43950150004) failed while opening PostgreSQL, before it ran collection. A direct read-only connection to the existing database independently returned the same quota error. No records were removed and no credentials, storage or billing settings were changed.

## Why it can recur

The old dashboard pulled full opportunity rows and appearances across the global catalogue before filtering. The scheduled collector called the dashboard as well as the browser. After the morning digest time it computed the dashboard twice per run even when the digest already existed. The workflow scheduled up to 48 wakeups per day. These paths created repeated database-to-app traffic. The exact division of November transfer among requests is unknown.

The revised dashboard selects only the columns needed to determine visibility, ranking and freshness, then loads full records for the top results. On the read-only local archive (10,793 opportunities), the whole response matched before and after. Estimated query-result data went from 134.8 MB to 0.23 MB per dashboard call, excluding database protocol overhead. This is a local measurement, not live Neon usage. The collector shares the dashboard result with the digest, limits historical health reads to records that need backfill and runs every two hours. The API returns a sanitized HTTP 503 when the database cannot accept connections.

## Recovery and follow-up

- [x] Confirm the quota and affected project from the provider alert and production connection checks.
- [ ] Validate and ship the narrower dashboard queries, smaller scheduled notification reads, less frequent collection and clear 503 outage message.
- [ ] Restore access at the next Neon billing reset, or have the account owner change plans in the [Neon Console](https://console.neon.tech/) if immediate access is needed. The [Neon recovery guidance](https://neon.com/docs/introduction/plans#how-do-i-restore-or-export-a-free-plan-project-that-hit-its-limits) confirms that transfer exhaustion blocks connections and exports until reset or upgrade; it does not delete data.
- [ ] After Neon accepts connections, verify the live health endpoint, authenticated dashboard and one scheduled or manual collection. Review transfer over the following billing period before increasing cadence.

The older local SQLite file is not a backup of the current hosted workspace. Do not replace production with it.
