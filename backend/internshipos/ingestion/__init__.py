"""Public source collection entry point used by API jobs and scheduled batches."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx

from .adapters import ADAPTERS
from .discovery import discover_company, freehire, jobspy, unstop, github_tracker
from .http import PublicHTTP, USER_AGENT
from .types import CollectionResult, SchemaError, Source, SourceError

ADAPTERS.update({"unstop": unstop, "freehire": freehire, "jobspy": jobspy, "github_tracker":github_tracker,
                 "linkedin": jobspy, "indeed": jobspy, "naukri": jobspy, "google": jobspy})
SUPPORTED_PROVIDERS = tuple(sorted(ADAPTERS))


class _Context:
    def __init__(self, source, http, max_pages, max_jobs, max_details):
        self.source, self.http = source, http
        self.max_pages, self.max_jobs, self.max_details = max_pages, max_jobs, max_details
        self.jobs = {}
        self.errors = []
        self.warnings = []
        self.scope = "full"
        self.complete = False
        self.reported_total = None
        self.detail_requests = 0

    def problem(self, message):
        if message not in self.errors:
            self.errors.append(message)

    def add(self, item):
        if not item.get("external_id") or not item.get("title"):
            self.problem("record_missing_identity_or_title")
            return 0
        key = item["external_id"]
        if key in self.jobs:
            return 0
        if len(self.jobs) >= self.max_jobs:
            raise SourceError("job_limit_reached")
        item["raw"] = {"source_payload": item.get("raw", {}),
                       "provider": self.source.provider, "source_url": self.source.url,
                       "description_complete": bool(item.get("description"))}
        self.jobs[key] = item
        return 1

    def finish(self, complete):
        self.complete = bool(complete)
        if not complete:
            self.problem("inventory_incomplete")

    async def detail_json(self, url, **kwargs):
        if self.detail_requests >= self.max_details:
            self.problem("detail_limit_reached")
            return None
        self.detail_requests += 1
        try:
            return await self.http.json("GET", url, **kwargs)
        except SourceError as exc:
            self.problem("detail_fetch_failed: " + str(exc))
            return None

    async def detail_text(self, url):
        if self.detail_requests >= self.max_details:
            self.problem("detail_limit_reached")
            return None
        self.detail_requests += 1
        try:
            return await self.http.text(url)
        except SourceError as exc:
            self.problem("detail_fetch_failed: " + str(exc))
            return None


async def collect_source(source, *, client=None, max_pages=25, max_jobs=5000,
                         max_details=80, timeout_seconds=120, resolve_dns=True,
                         max_requests=160) -> CollectionResult:
    """Collect one source without mutating the DB. Caller persists every result.

    `complete` requires adapter termination and no errors. `coverage_scope`
    independently protects filtered/discovery queries from lifecycle sweeps.
    Inject an httpx MockTransport and resolve_dns=False for deterministic tests.
    """
    source = Source.from_value(source)
    adapter = ADAPTERS.get(source.provider)
    if source.config.get("refresh_external_ids") or source.config.get("refresh_jobs"):
        from .refresh import targeted_refresh
        adapter = targeted_refresh
    if adapter is None:
        return CollectionResult(error=f"unsupported_provider:{source.provider}; use generic JSON-LD or manual capture",
                                metadata={"provider": source.provider, "source_url": source.url})
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), trust_env=False,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html,application/xml;q=0.9,*/*;q=0.8"})
    http = PublicHTTP(client, max_requests=max_requests, resolve_dns=resolve_dns)
    context = _Context(source, http, max(1, min(max_pages, 100)), max(1, min(max_jobs, 20000)), max(0, min(max_details, 500)))
    started = time.monotonic()
    try:
        await asyncio.wait_for(adapter(context), timeout=max(5, min(timeout_seconds, 600)))
    except asyncio.TimeoutError:
        context.problem("collection_time_budget_exhausted")
    except (SourceError, ValueError, KeyError, TypeError, AttributeError) as exc:
        context.problem(str(exc) if isinstance(exc, SourceError) else f"schema_error:{type(exc).__name__}:{str(exc)[:200]}")
    finally:
        if own:
            await client.aclose()
    jobs = list(context.jobs.values())
    return CollectionResult(jobs=jobs, complete=context.complete and not context.errors,
        error="; ".join(context.errors) or None, coverage_scope=context.scope,
        observed_count=len(jobs), metadata={"provider": source.provider, "source_url": source.url,
            "observed_at": datetime.now(timezone.utc).isoformat(), "reported_total": context.reported_total,
            "requests": http.requests, "http_statuses": dict(http.status_counts),
            "elapsed_seconds": round(time.monotonic() - started, 3), "detail_requests": context.detail_requests, "next_detail_cursor":getattr(context,"next_detail_cursor",None),
            "description_count": sum(bool(x["description"]) for x in jobs), "errors": context.errors, "warnings": context.warnings})


__all__ = ["collect_source", "discover_company", "CollectionResult", "Source", "SUPPORTED_PROVIDERS"]
