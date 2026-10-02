# Public ingestion

`await collect_source(source)` returns jobs, completeness, coverage scope, errors and request metadata without touching the database. The worker persists its result through `service.ingest_batch`. No import performs a fetch.

Structured adapters: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Oracle Recruiting, Eightfold, Workable, Recruitee, Personio XML, Amazon, Breezy, Pinpoint and BambooHR. JSON-LD supports individual pages and bounded linked listings, including Internshala. Unstop and Freehire have dedicated public discovery adapters. JobSpy is isolated and optional. A provider name with no adapter returns an explicit unsupported result; there are no placeholder success responses.

The 200-company seed and 243 board candidates come from a curated MIT Job Seek snapshot plus named India employers. Known erroneous registry name/domain mappings were excluded. Company seed trust does not verify every ATS association or job. Full license notices are in `ATTRIBUTION.md`.

Only `complete=True`, `error=None`, `coverage_scope='full'` can support absence detection in the persistence layer. Query, discovery and targeted saved-job refresh results cannot. Failed detail requests, caps and malformed schemas remain explicit. A configured discovery window can complete successfully while metadata warns that it is not the entire inventory.

## Run and verify

From `backend/` with the app environment active:

```powershell
python -m pytest tests/test_ingestion.py -q
python -m internshipos.ingestion --provider lever --url https://jobs.lever.co/meesho --company Meesho --domain meesho.io --max-pages 1 --output collection.json
```

The optional JobSpy runtime can use a separate Python 3.11 environment with `requirements-jobspy.txt`. Its older NumPy pin does not install cleanly on Python 3.13. Set `JOBSPY_PYTHON` to that environment's Python executable. The app invokes `jobspy_worker.py` directly so this environment needs JobSpy's dependencies, not the core application. No research environment is used at runtime. Missing optional dependencies produce source-health errors; the rest of collection continues. Naukri starts disabled because a challenge was observed; manual capture remains available.

## Saved jobs and discovery

`source.config.refresh_external_ids` plus `refresh_jobs` activates direct saved-job hydration with `coverage_scope='targeted'`. Include external ID, canonical URL, requisition ID, title, opportunity ID and company identity. Workday uses the saved canonical path, avoiding the first-page/detail-budget problem. A 404 stays uncertain. Unambiguous full JSON-LD is the fallback for other saved job pages; a short search snippet does not count as a refreshed JD.

`discover_company(name, domain, careers_url, trusted_domain=False)` reads the supplied public site and a few linked careers pages. It returns evidence, `discovery_status`, `checked_at` and `retry_after_hours`. Pass `trusted_domain=True` only for an employer domain already verified by the application/user. A link or redirect from that official domain to a recognized ATS can verify the association. A reachable URL or an unlinked user-supplied ATS URL alone never verifies a new company. Import the source's returned verification flag only with its recorded binding evidence.

Callers should schedule candidates by their last discovery attempt and returned retry interval, rather than repeatedly selecting the first unverified rows. Defaults: missing domain 14 days, fetch failure 24 hours, no mapping 7 days, mapping found 30 days. A changed/new official domain can trigger an explicit earlier attempt.

## Remaining practical limits

Workday queries that still reach its cap return incomplete; they are not silently considered exhaustive. India and early-career facet IDs are discovered from each tenant's response. Amazon requires `normalized_country_code[]=IND`; `loc_query=India` alone was observed to leave the result global. Some custom sites need individual adapters or manual capture. Broad national coverage, uptime and exclusive yield have not been claimed from the bounded checks. `fixtures/live_smoke_summary.json` and per-source samples record actual integration observations; successful fixture tests are separate from live provider health.
