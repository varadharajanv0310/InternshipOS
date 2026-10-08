"""Bounded public LinkedIn discovery: enumerate before fetching target details.

Uses the ordinary unauthenticated guest routes also used by JobSpy. No cookies,
account sessions, proxies, challenge solving or successful-empty error fallback.
"""
from __future__ import annotations

import asyncio
import re
import time
import weakref
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .adapters import detail_candidate, inventory_finished, rotating_details
from .parsing import date_value, job
from .types import SchemaError, SourceError

ORIGIN = "https://www.linkedin.com"
SEARCH = ORIGIN + "/jobs-guest/jobs/api/seeMoreJobPostings/search"
_PACING = weakref.WeakKeyDictionary()


async def _request(c, url, **kwargs):
    """Share a conservative public-request pace across concurrent searches."""
    loop = asyncio.get_running_loop()
    state = _PACING.setdefault(loop, [asyncio.Lock(), 0.0])
    async with state[0]:
        delay = max(0.0, state[1] + 1.0 - time.monotonic())
        if delay:
            await asyncio.sleep(delay)
        try:
            return await c.http.request("GET", url, **kwargs)
        finally:
            state[1] = time.monotonic()


def native_id(url):
    parsed = urlsplit(str(url or ""))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "linkedin.com" or host.endswith(".linkedin.com")) or parsed.username or parsed.password:
        return None
    if "/jobs/view/" not in parsed.path and "/jobs-guest/jobs/api/jobPosting/" not in parsed.path:
        return None
    match = re.search(r"(?:-|/)(\d+)$", parsed.path.rstrip("/"))
    return match[1] if match else None


def _text(node):
    return node.get_text(" ", strip=True) if node else ""


def parse_card(source, card):
    anchor = card.select_one("a.base-card__full-link[href]")
    title = card.select_one(".base-search-card__title")
    employer = card.select_one(".base-search-card__subtitle")
    link = anchor.get("href") if anchor else None
    ident = native_id(link)
    urn = card.get("data-entity-urn")
    if not ident or not _text(title) or not _text(employer):
        raise SchemaError("linkedin_card_identity_title_or_employer_missing")
    if urn and urn != "urn:li:jobPosting:" + ident:
        raise SchemaError("linkedin_card_identity_mismatch")
    # Regional LinkedIn hosts and tracking query parameters share one native ID.
    canonical = ORIGIN + "/jobs/view/" + ident
    posted = card.select_one("time[datetime]")
    location = _text(card.select_one(".job-search-card__location"))
    return job(source, ident, _text(title), url=canonical, location=location,
               company_name=_text(employer), company_domain=None,
               posted_at=date_value(posted.get("datetime")) if posted else None,
               raw={"native_job_id": ident, "public_listing_url": link,
                    "description_complete": False},
               evidence=[{"kind": "public_discovery_listing", "source_url": source.url,
                          "native_job_id": ident, "company_verification": "unverified_discovery"}])


def _same_name(first, second):
    return re.sub(r"\W+", " ", first.casefold()).strip() == re.sub(r"\W+", " ", second.casefold()).strip()


def parse_detail(source, listing, html, final_url):
    if native_id(final_url) != listing["external_id"]:
        raise SchemaError("linkedin_detail_redirect_identity_mismatch")
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one(".top-card-layout")
    description_section = soup.select_one(".description")
    title = main.select_one(".top-card-layout__title") if main else None
    employer = main.select_one(".topcard__org-name-link") if main else None
    description = description_section.select_one(".show-more-less-html__markup") if description_section else None
    if not title or not employer or not description or not _text(description):
        raise SchemaError("linkedin_detail_primary_schema_missing")
    if not _same_name(_text(title), listing["title"]) or not _same_name(_text(employer), listing["company_name"]):
        raise SchemaError("linkedin_detail_title_or_employer_mismatch")
    canonical = soup.select_one("link[rel=canonical][href]")
    if canonical and native_id(canonical["href"]) != listing["external_id"]:
        raise SchemaError("linkedin_detail_canonical_identity_mismatch")
    item = job(source, listing["external_id"], listing["title"],
               description=str(description), url=listing["canonical_url"],
               location=listing["location"], company_name=listing["company_name"],
               company_domain=None, posted_at=listing.get("posted_at"),
               raw={**listing.get("raw", {}).get("source_payload", listing.get("raw", {})), "description_complete": True,
                    "detail_url": final_url},
               evidence=[*listing.get("evidence", []), {"kind": "public_discovery_detail",
                         "source_url": final_url, "native_job_id": listing["external_id"],
                         "company_verification": "unverified_discovery"}])
    return item


async def collect(c):
    c.scope = "discovery"
    wanted = max(1, min(int(c.source.config.get("results_wanted", 30)), 100))
    records = []
    terminal = False
    offset = 0
    for page in range(c.max_pages):
        response = await _request(c, SEARCH, params={
            "keywords": c.source.config.get("search_term", "software intern"),
            "location": c.source.config.get("location", "India"), "start": offset})
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(".base-search-card")
        if not cards:
            if response.text.strip():
                raise SchemaError("linkedin_listing_schema_missing")
            terminal = True
            break
        added = 0
        for card in cards:
            listing = parse_card(c.source, card)
            if len(c.jobs) >= wanted:
                break
            if c.add(listing):
                records.append(listing)
                added += 1
        if not added:
            raise SourceError("linkedin_search_repeated_page")
        offset += len(cards)
        if len(c.jobs) >= wanted:
            terminal = True
            c.warnings.append("bounded_discovery_window; not_a_full_inventory")
            break
    inventory_finished(c, terminal)
    # Search windows always start fresh. Detail rotation is independent.
    c.next_listing_cursor = 0
    c.description_target_count = sum(detail_candidate(item) for item in records) if c.source.config.get("detail_target_only") else len(records)
    if c.max_details == 0:
        c.description_scope = "listing_only"
        c.description_complete = False
    else:
        c.description_scope = "target_candidates" if c.source.config.get("detail_target_only") else "listed_records"
        async def enrich(listing):
            c.detail_requests += 1
            url = ORIGIN + "/jobs-guest/jobs/api/jobPosting/" + listing["external_id"]
            try:
                response = await _request(c, url)
                return parse_detail(c.source, listing, response.text, str(response.url))
            except SourceError as exc:
                c.problem("detail_fetch_failed: " + str(exc))
                if "access_restricted_or_challenged" in str(exc) or "challenge_page" in str(exc):
                    raise SourceError("linkedin_detail_requests_paused_after_access_restriction") from exc
                return None
        await rotating_details(c, records, enrich)
        c.description_complete = not c.errors and (c.description_target_count == 0 or all(
            item.get("description") for item in c.jobs.values()
            if not c.source.config.get("detail_target_only") or detail_candidate(item)))
    if not terminal:
        c.problem("page_limit_reached")
    c.finish(terminal)
