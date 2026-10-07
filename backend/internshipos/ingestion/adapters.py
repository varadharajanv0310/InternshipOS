"""Structured public ATS adapters. Completeness is a result, never an assumption.

Endpoint behavior was checked against the saved Phase 0 experiments. Provider
protocols are implemented independently; small parsing techniques are informed
by MIT ats-scrapers/Freehire (see ATTRIBUTION.md).
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from .parsing import compensation, date_value, job, jsonld_objects, location_text, parse_jsonld, plain
from .types import SchemaError, SourceError


def rows_at(payload, key):
    value = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(value, list):
        raise SchemaError(f"expected_array:{key}")
    return value


def cursor_at(source, key="detail_cursor"):
    """Read a nonnegative checkpoint without accepting malformed registry data."""
    try:
        return max(0, int(source.config.get(key, 0)))
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"invalid_cursor:{key}") from exc


def reported_count(value, *, required=False):
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isdigit():
        raise SchemaError("invalid_reported_inventory_count")
    return int(value)


def inventory_finished(c, complete):
    """Listing coverage is independent of the bounded description pass."""
    c.inventory_complete = bool(complete)
    c.inventory_observed_count = len(c.jobs)


def update_detail(c, item):
    """Replace one already enumerated listing with its fetched full details."""
    key = item.get("external_id")
    if key not in c.jobs:
        c.add(item)
        return
    item["raw"] = {"source_payload": item.get("raw", {}),
                   "provider": c.source.provider, "source_url": c.source.url,
                   "description_complete": bool(item.get("description"))}
    c.jobs[key] = item


def detail_candidate(item):
    from ..search_policy import location_decision, retain_new_candidate
    if retain_new_candidate(item):
        return True
    return (location_decision(item.get("location"), item.get("country"), item.get("work_mode")) == "allowed"
            and bool(re.fullmatch(r"(?:intern|internship|(?:engineering|technical|technology) intern(?:ship)?)",
                                 item.get("title", "").strip(), re.I)))


async def rotating_details(c, records, enrich):
    """Enumerate first; spend description requests on target roles before history.

    Target and secondary refresh checkpoints advance only after a request finishes.
    A shrinking inventory wraps safely; a timeout retries the interrupted record.
    Historic foreign appearances use spare budget rather than delaying India roles.
    """
    async def group(selected_records, key="detail_cursor", required=True):
        attribute = "next_" + key
        if not selected_records:
            setattr(c, attribute, 0)
            return
        start = cursor_at(c.source, key) % len(selected_records)
        remaining = max(0, c.max_details - c.detail_requests)
        selected = selected_records[start:start + remaining]
        setattr(c, attribute, start)
        for index, record in enumerate(selected, start):
            setattr(c, attribute, index)
            item = await enrich(record)
            if item is not None:
                update_detail(c, item)
                if not item.get("description"):
                    c.problem("full_description_unavailable")
            setattr(c, attribute, index + 1 if index + 1 < len(selected_records) else 0)
        if len(selected) < len(selected_records):
            if required:
                c.problem("detail_limit_reached")
            else:
                c.warnings.append("retained_foreign_detail_refresh_deferred; target_details_take_priority")
    if not c.source.config.get("detail_target_only"):
        await group(records)
        return
    retained = {str(x) for x in c.source.config.get("retained_external_ids", [])}
    def item_for(record):
        bullets = record.get("bulletFields") or []
        if not isinstance(bullets, list):
            bullets = []
        identifiers = [record.get("external_id"), record.get("shortcode"), record.get("id"), record.get("Id"),
                       record.get("_id"), record.get("externalPath"), record.get("RequisitionNumber")] + bullets
        return next((c.jobs[str(key)] for key in identifiers if key is not None and str(key) in c.jobs), None)
    prioritized, refresh_existing = [], []
    for record in records:
        item = item_for(record)
        if item is not None and detail_candidate(item):
            prioritized.append(record)
        elif item is not None and item["external_id"] in retained:
            refresh_existing.append(record)
    c.warnings.append("detail_scope:technical_internship_candidates_and_retained_appearances")
    await group(prioritized)
    await group(refresh_existing, "retained_detail_cursor", required=False)

def slug(source, host_suffix=None):
    config = source.config
    value = config.get("token") or config.get("slug") or config.get("tenant") or config.get("company_identifier")
    if value:
        return quote(str(value), safe="-_ .".replace(" ", ""))
    parsed = urlsplit(source.url)
    host = parsed.hostname or ""
    parts = [p for p in parsed.path.split("/") if p]
    if host_suffix and host.endswith(host_suffix):
        return quote(host.split(".")[0], safe="-_")
    if not parts:
        raise SourceError("missing_company_slug")
    return quote(parts[0], safe="-_")


async def greenhouse(c):
    token = slug(c.source)
    if "/boards/" in c.source.url:
        token = c.source.url.split("/boards/", 1)[1].split("/")[0]
    api = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    try:
        payload = await c.http.json("GET", api, params={"content": "true"})
    except SourceError as exc:
        if str(exc) != "response_size_limit_exceeded":
            raise
        # Large boards can exceed the bounded transport when every JD is embedded.
        # The lightweight inventory still provides every public listing identity.
        c.warnings.append("oversized_embedded_descriptions; using_listing_and_bounded_details")
        c.source.config = {"detail_target_only": True, **c.source.config}
        payload = await c.http.json("GET", api)
    items = rows_at(payload, "jobs")
    c.reported_total = reported_count((payload.get("meta") or {}).get("total", len(items)), required=True)
    def parse(x):
        pay = (x.get("pay_input_ranges") or [{}])[0]
        return job(c.source, x.get("id"), x.get("title"), description=x.get("content"),
                  url=x.get("absolute_url"), location=x.get("location"), raw=x,
                  requisition_id=x.get("requisition_id"), posted_at=date_value(x.get("first_published")), deadline=date_value(x.get("application_deadline")),
                  compensation=compensation(pay.get("min_cents") / 100 if pay.get("min_cents") is not None else None,
                    pay.get("max_cents") / 100 if pay.get("max_cents") is not None else None, pay.get("currency_type"), "year" if pay else None))
    records = []
    for x in items:
        item = parse(x)
        c.add(item)
        if not item["description"]:
            records.append(x)
    listing_complete = len(c.jobs) == c.reported_total
    inventory_finished(c, listing_complete)
    if records:
        c.warnings.append("detail_scope:technical_internship_candidates")
        async def enrich(x):
            detail = await c.detail_json(f"{api}/{quote(str(x.get('id')), safe='')}")
            return parse({**x, **detail}) if isinstance(detail, dict) else parse(x)
        await rotating_details(c, records, enrich)
    else:
        c.next_detail_cursor = 0
    c.finish(listing_complete)


async def lever(c):
    token = slug(c.source)
    host = "api.eu.lever.co" if "eu.lever.co" in c.source.url else "api.lever.co"
    start = cursor_at(c.source, "listing_cursor") // 100
    if start:
        c.scope = "query"
    c.next_listing_cursor = start * 100
    for page in range(start, start + c.max_pages):
        payload = await c.http.json("GET", f"https://{host}/v0/postings/{token}", params={"mode": "json", "skip": page * 100, "limit": 100})
        if not isinstance(payload, list):
            raise SchemaError("expected_lever_postings_array")
        new = 0
        for x in payload:
            cats = x.get("categories") or {}
            desc = (x.get("description") or x.get("descriptionPlain") or "") + "\n" + "\n".join(
                f"<h3>{i.get('text', '')}</h3>{i.get('content', '')}" for i in (x.get("lists") or [])) + (x.get("additional") or "")
            salary = x.get("salaryRange") or {}
            new += c.add(job(c.source, x.get("id"), x.get("text"), description=desc,
                url=x.get("hostedUrl"), apply_url=x.get("applyUrl") or x.get("hostedUrl"),
                location=cats.get("allLocations") or cats.get("location"), raw=x,
                employment_type=cats.get("commitment"), work_mode=x.get("workplaceType") or "unknown",
                posted_at=date_value(x.get("createdAt")),
                compensation=compensation(salary.get("min"), salary.get("max"), salary.get("currency"), salary.get("interval"))))
        c.next_listing_cursor = (page + 1) * 100
        if not new and payload:
            raise SourceError("pagination_repeated_page")
        if len(payload) < 100:
            c.next_listing_cursor = 0
            inventory_finished(c, start == 0)
            c.finish(True)
            return
    c.problem("page_limit_reached")


async def ashby(c):
    token = slug(c.source)
    payload = await c.http.json("GET", f"https://api.ashbyhq.com/posting-api/job-board/{token}", params={"includeCompensation": "true"})
    for x in rows_at(payload, "jobs"):
        c.add(job(c.source, x.get("id") or x.get("jobUrl"), x.get("title"),
            description=x.get("descriptionHtml") or x.get("descriptionPlain"), url=x.get("jobUrl"),
            apply_url=x.get("applyUrl") or x.get("jobUrl"), location=x.get("location"), raw=x,
            work_mode=x.get("workplaceType") or ("remote" if x.get("isRemote") is True else "unknown"),
            employment_type=x.get("employmentType"), posted_at=date_value(x.get("publishedAt")),
            compensation=compensation(label=(x.get("compensation") or {}).get("compensationTierSummary"))))
    c.finish(True)


async def smartrecruiters(c):
    token = slug(c.source)
    records = []
    listing_complete = False
    def parse(x, detail=None):
        ident = x.get("id")
        d = detail or x
        sections = (d.get("jobAd") or {}).get("sections") or {}
        desc = "\n".join(v.get("text", "") for v in sections.values() if isinstance(v, dict))
        return job(c.source, ident, d.get("name") or x.get("name"), description=desc,
            url=d.get("postingUrl") or f"https://jobs.smartrecruiters.com/{token}/{ident}",
            apply_url=d.get("applyUrl") or d.get("postingUrl") or f"https://jobs.smartrecruiters.com/{token}/{ident}",
            location=d.get("location") or x.get("location"), raw={"listing": x, "detail": detail},
            country=(d.get("location") or x.get("location") or {}).get("country"),
            work_mode="remote" if (d.get("location") or x.get("location") or {}).get("remote") is True else "unknown",
            posted_at=date_value(d.get("releasedDate") or x.get("releasedDate")),
            employment_type=(d.get("typeOfEmployment") or x.get("typeOfEmployment") or {}).get("label"))
    for page in range(c.max_pages):
        data = await c.http.json("GET", f"https://api.smartrecruiters.com/v1/companies/{token}/postings", params={"limit": 100, "offset": page * 100})
        items = rows_at(data, "content")
        reported = reported_count(data.get("totalFound"))
        if c.reported_total is not None and reported != c.reported_total:
            c.problem("inventory_changed_during_scan")
        c.reported_total = reported
        new = 0
        for x in items:
            accepted = c.add(parse(x))
            new += accepted
            if accepted:
                records.append(x)
        if items and not new:
            c.problem("pagination_repeated_page")
            break
        if c.reported_total is not None and len(c.jobs) >= int(c.reported_total):
            listing_complete = "inventory_changed_during_scan" not in c.errors
            break
        if len(items) < 100:
            listing_complete = c.reported_total is None or len(c.jobs) >= int(c.reported_total)
            break
    else:
        c.problem("page_limit_reached")
    inventory_finished(c, listing_complete)
    async def enrich(x):
        detail = await c.detail_json(f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{quote(str(x.get('id')), safe='')}")
        return parse(x, detail)
    await rotating_details(c, records, enrich)
    c.finish(listing_complete)


def workday_listing_identifiers(record):
    """Bullet order varies by tenant; locations are not requisition identities."""
    path = str(record.get("externalPath") or "")
    bullets = record.get("bulletFields") or []
    if not isinstance(bullets, list):
        bullets = []
    candidates = [str(value) for value in bullets if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value)]
    for candidate in candidates:
        if path.rsplit("/", 1)[-1] == candidate or path.endswith("_" + candidate):
            return candidate, candidate
    for candidate in candidates:
        if re.search("_" + re.escape(candidate) + r"-\d+$", path):
            # Multiple public posting variants can share one requisition. Keep
            # their paths distinct while recording the explicitly supplied req.
            return path, candidate
    return path, None


def workday_target(source):
    p = urlsplit(source.url)
    if not p.hostname or not re.search(r"\.myworkday(?:jobs|site)\.com$", p.hostname):
        raise SourceError("invalid_workday_host")
    parts = [x for x in p.path.split("/") if x]
    if parts[:2] == ["wday", "cxs"] and len(parts) >= 4:
        tenant, site = parts[2:4]
    else:
        if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
            parts.pop(0)
        if parts[:1] == ["recruiting"] and len(parts) >= 3:
            tenant, site = parts[1:3]
        else:
            tenant = source.config.get("tenant") or p.hostname.split(".")[0]
            site = source.config.get("site") or (parts[0] if parts else source.config.get("board"))
    if not site:
        raise SourceError("missing_workday_site")
    return source.origin, tenant, site


async def workday(c):
    origin, tenant, site = workday_target(c.source)
    api = f"{origin}/wday/cxs/{quote(tenant, safe='')}/{quote(site, safe='')}"
    query = c.source.config.get("search_text", "")
    facets = dict(c.source.config.get("applied_facets", {}))
    country_name = c.source.config.get("country_name")
    early_career = c.source.config.get("early_career", False)
    if country_name or early_career:
        c.scope = "query"
        initial = await c.http.json("POST", f"{api}/jobs", json={"limit": 20, "offset": 0, "searchText": query, "appliedFacets": facets})
        def walk(nodes):
            for node in nodes:
                if isinstance(node, dict):
                    yield node
                    yield from walk(node.get("values", []))
        found_country = False
        for facet in walk(initial.get("facets") or []):
            parameter = facet.get("facetParameter")
            if not parameter:
                continue
            values = [v for v in facet.get("values", []) if isinstance(v, dict) and v.get("id")]
            if country_name:
                chosen = [v["id"] for v in values if str(v.get("descriptor", "")).casefold() == str(country_name).casefold()]
                if chosen:
                    facets[parameter] = chosen
                    found_country = True
            if early_career and (parameter.lower() in {"workersubtype", "jobtype", "jobtypes"} or facet.get("descriptor") == "Job Type"):
                chosen = [v["id"] for v in values if re.search(r"\bintern|\bapprentice|\btrainee|new college grad|early career", str(v.get("descriptor", "")), re.I)]
                if chosen:
                    facets[parameter] = chosen
                    query = ""  # A type facet also admits separately classified graduate/apprentice roles.
        if country_name and not found_country:
            c.warnings.append("country_facet_unavailable; locations_must_be_filtered_after_collection")
    if query or facets:
        c.scope = "query"
    offset = cursor_at(c.source, "listing_cursor")
    initial_offset = offset
    c.next_listing_cursor = offset
    if initial_offset:
        c.scope = "query"
        c.warnings.append("continued_listing_segment; full_inventory_not_proven")
    async def listing_page(page_offset):
        data = await c.http.json("POST", f"{api}/jobs", json={"limit": 20, "offset": page_offset, "searchText": query, "appliedFacets": facets})
        items = rows_at(data, "jobPostings")
        total = data.get("total")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise SchemaError("missing_workday_total")
        return items, total
    if initial_offset:
        # Later Workday pages can report total=0 while still returning jobs.
        # A resumed segment needs a fresh head for its final query/facets, not
        # the unfiltered facet-discovery count or a previous run's cached total.
        head_items, c.reported_total = await listing_page(0)
        if c.reported_total > 0 and not head_items:
            c.problem("workday_pagination_incomplete_or_repeated")
    records = []
    listing_complete = False
    def parse(x, detail=None):
        d = (detail or {}).get("jobPostingInfo") or {}
        path = x.get("externalPath")
        ident, requisition = workday_listing_identifiers(x)
        locations = [d.get("location")] + (d.get("additionalLocations") or [])
        return job(c.source, ident, d.get("title") or x.get("title"),
            description=d.get("jobDescription"), url=f"{origin}/{site}{path}",
            location=list(filter(None, locations)) or x.get("locationsText"),
            raw={"listing": x, "detail": detail}, requisition_id=d.get("jobReqId") or requisition,
            posted_at=date_value(d.get("startDate")), deadline=date_value(d.get("endDate")),
            employment_type=d.get("timeType"), work_mode=d.get("remoteType") or "unknown")
    for _ in range(c.max_pages):
        items, total = await listing_page(offset)
        if c.reported_total is None:
            c.reported_total = total
        expected_total = c.reported_total
        if expected_total >= 2000 or total >= 2000:
            c.problem("workday_query_cap_requires_partitioning")
        new = 0
        for x in items:
            path = x.get("externalPath")
            if not path:
                c.problem("workday_missing_external_path"); continue
            accepted = c.add(parse(x))
            new += accepted
            if accepted:
                records.append(x)
        zero_total_sentinel = (offset > 0 and total == 0 and expected_total > 0
                               and bool(items) and new == len(items))
        if (total != expected_total and not zero_total_sentinel) or (offset == 0 and total == 0 and items):
            c.problem("inventory_changed_during_scan")
        if items and new != len(items):
            c.problem("workday_pagination_incomplete_or_repeated")
        if items and not new:
            c.problem("workday_pagination_incomplete_or_repeated")
            break
        offset += len(items)
        c.next_listing_cursor = offset
        if offset > expected_total:
            c.problem("inventory_changed_during_scan")
        if offset >= expected_total:
            c.next_listing_cursor = 0
            listing_complete = (initial_offset == 0 and len(c.jobs) >= expected_total and expected_total < 2000
                                and "inventory_changed_during_scan" not in c.errors
                                and "workday_pagination_incomplete_or_repeated" not in c.errors)
            break
        if not items or not new:
            c.next_listing_cursor = 0 if not items else offset
            c.problem("workday_pagination_incomplete_or_repeated")
            break
    else:
        c.problem("page_limit_reached")
    inventory_finished(c, listing_complete)
    async def enrich(x):
        detail = await c.detail_json(api + x["externalPath"])
        return parse(x, detail)
    await rotating_details(c, records, enrich)
    c.finish(listing_complete)


async def oracle(c):
    site_match = re.search(r"/sites/([^/?#]+)", c.source.url)
    site = c.source.config.get("site_number") or c.source.config.get("site") or (site_match.group(1) if site_match else "CX_1")
    api = c.source.origin + "/hcmRestApi/resources/latest/"
    records = []
    listing_complete = False
    def parse(x, detail=None):
        ident = x.get("Id") or x.get("RequisitionNumber")
        detail_items = (detail or {}).get("items") or []
        d = detail_items[0] if detail_items else {}
        desc = "\n".join(d.get(k) or "" for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"))
        if not d.get("ExternalDescriptionStr"):
            desc = ""  # Search previews must not advance the full-JD refresh clock.
        url = f"{c.source.origin}/hcmUI/CandidateExperience/en/sites/{site}/job/{ident}"
        return job(c.source, ident, x.get("Title"), description=desc, url=url,
            location=x.get("PrimaryLocation"), country=x.get("PrimaryLocationCountry"), raw={"listing": x, "detail": d},
            requisition_id=x.get("RequisitionNumber") or str(ident), posted_at=date_value(x.get("PostedDate")),
            deadline=date_value(x.get("PostingEndDate")), employment_type=x.get("JobType") or x.get("WorkerType"),
            work_mode={"ORA_REMOTE": "remote", "ORA_HYBRID": "hybrid", "ORA_ON_SITE": "onsite"}.get(x.get("WorkplaceTypeCode"), "unknown"))
    for page in range(c.max_pages):
        finder = f"findReqs;siteNumber={site},limit=100,offset={page * 100}"
        if c.source.config.get("keyword"):
            finder += ",keyword=" + str(c.source.config["keyword"])
            c.scope = "query"
        data = await c.http.json("GET", api + "recruitingCEJobRequisitions", params={"onlyData": "true", "expand": "requisitionList", "finder": finder})
        envelope = rows_at(data, "items")
        if not envelope or not isinstance(envelope[0], dict) or "requisitionList" not in envelope[0]:
            raise SchemaError("oracle_requisition_envelope_missing")
        items = rows_at(envelope[0], "requisitionList")
        total = envelope[0].get("TotalJobsCount")
        reported = reported_count(total)
        if c.reported_total is not None and reported != c.reported_total:
            c.problem("inventory_changed_during_scan")
        c.reported_total = reported
        new = 0
        for x in items:
            accepted = c.add(parse(x))
            new += accepted
            if accepted:
                records.append(x)
        if items and not new:
            c.problem("pagination_repeated_page")
            break
        if reported is not None and len(c.jobs) >= reported:
            listing_complete = "inventory_changed_during_scan" not in c.errors
            break
        if len(items) < 100:
            listing_complete = reported is None
            break
    else:
        c.problem("page_limit_reached")
    inventory_finished(c, listing_complete)
    async def enrich(x):
        ident = x.get("Id") or x.get("RequisitionNumber")
        detail = await c.detail_json(api + "recruitingCEJobRequisitionDetails", params={"onlyData": "true", "finder": f"ById;Id={ident}"})
        item = parse(x, detail)
        if detail is not None and not item["description"]:
            c.problem("oracle_full_description_unavailable")
        return item
    await rotating_details(c, records, enrich)
    c.finish(listing_complete)


async def eightfold(c):
    domain = c.source.config.get("domain") or c.source.company_domain
    if not domain:
        raise SourceError("eightfold_company_domain_required")
    query = c.source.config.get("query", "")
    if query:
        c.scope = "query"
    start = cursor_at(c.source, "listing_cursor")
    initial_offset = start
    c.next_listing_cursor = start
    if initial_offset:
        c.scope = "query"
        c.warnings.append("continued_listing_segment; full_inventory_not_proven")
    records = []
    listing_complete = False
    def parse(x, detail=None):
        d = (detail or {}).get("data") or {}
        ident = x.get("id")
        return job(c.source, ident, x.get("name"), description=d.get("jobDescription") or x.get("job_description"),
            url=x.get("positionUrl") or f"{c.source.origin}/careers/job/{ident}", location=x.get("locations"),
            raw={"listing": x, "detail": d}, requisition_id=x.get("atsJobId") or x.get("displayJobId"),
            posted_at=date_value(x.get("postedTs")), work_mode=x.get("workLocationOption") or "unknown")
    for _ in range(c.max_pages):
        payload = await c.http.json("GET", c.source.origin + "/api/pcsx/search", params={"domain": domain, "query": query, "start": start, "sort_by": "timestamp"})
        data = payload.get("data") or {}
        items = rows_at(data, "positions")
        reported = reported_count(data.get("count"))
        if c.reported_total is not None and reported != c.reported_total:
            c.problem("inventory_changed_during_scan")
        c.reported_total = reported
        new = 0
        for x in items:
            accepted = c.add(parse(x))
            new += accepted
            if accepted:
                records.append(x)
        if items and not new:
            c.problem("pagination_repeated_page")
            break
        start += len(items)
        c.next_listing_cursor = start
        if reported is not None and start >= reported:
            c.next_listing_cursor = 0
            listing_complete = initial_offset == 0 and len(c.jobs) >= reported and "inventory_changed_during_scan" not in c.errors
            break
        if not items:
            c.next_listing_cursor = 0
            listing_complete = reported is None and initial_offset == 0
            break
    else:
        c.problem("page_limit_reached")
    inventory_finished(c, listing_complete)
    async def enrich(x):
        detail = await c.detail_json(c.source.origin + "/api/pcsx/position_details", params={"position_id": x.get("id"), "domain": domain, "hl": "en"})
        return parse(x, detail)
    await rotating_details(c, records, enrich)
    c.finish(listing_complete)

async def workable(c):
    token = slug(c.source)
    payload = await c.http.json("GET", f"https://apply.workable.com/api/v1/widget/accounts/{token}")
    records = rows_at(payload, "jobs")
    def parse(x, desc=None):
        ident = x.get("shortcode") or x.get("id")
        return job(c.source, ident, x.get("title"), description=desc or x.get("description"),
            url=x.get("url") or f"https://apply.workable.com/{token}/j/{ident}/", location=x.get("location"), raw=x,
            posted_at=date_value(x.get("published_on") or x.get("created_at")), employment_type=x.get("employment_type"),
            country=x.get("country"), work_mode="remote" if x.get("telecommuting") is True else "unknown")
    for x in records:
        c.add(parse(x))
    listing_complete = len(c.jobs) == len(records)
    inventory_finished(c, listing_complete)
    async def enrich(x):
        ident = x.get("shortcode") or x.get("id")
        desc = await c.detail_text(f"https://apply.workable.com/{token}/jobs/view/{ident}.md")
        return parse(x, desc)
    await rotating_details(c, [x for x in records if not x.get("description")], enrich)
    c.finish(listing_complete)


async def recruitee(c):
    token = slug(c.source, ".recruitee.com")
    payload = await c.http.json("GET", f"https://{token}.recruitee.com/api/offers/")
    for x in rows_at(payload, "offers"):
        salary = x.get("salary") or {}
        if not isinstance(salary, dict):
            salary = {"label": str(salary)}
        c.add(job(c.source, x.get("id") or x.get("slug"), x.get("title"),
            description=(x.get("description") or "") + "\n" + (x.get("requirements") or ""),
            url=x.get("careers_url") or f"https://{token}.recruitee.com/o/{x.get('slug')}",
            location=x.get("location") or x.get("locations"), raw=x, country=x.get("country_code"),
            posted_at=date_value(x.get("published_at")), employment_type=x.get("employment_type_code"),
            work_mode="remote" if x.get("remote") is True else "unknown",
            compensation=compensation(salary.get("min"), salary.get("max"), salary.get("currency"), salary.get("period"), salary.get("label"))))
    c.finish(True)


async def personio(c):
    # The published XML feed includes full descriptions and does not need a browser.
    from defusedxml import ElementTree
    text = await c.http.text(c.source.origin + "/xml")
    try:
        root = ElementTree.fromstring(text)
    except Exception as exc:
        raise SchemaError("invalid_personio_xml") from exc
    if root.tag.split("}")[-1] not in {"workzag-jobs", "jobs", "positions"}:
        raise SchemaError("unexpected_personio_xml_root")
    for x in root.findall(".//position"):
        ident = x.findtext("id")
        desc = "\n".join("<h3>" + (d.findtext("name") or "") + "</h3>" + (d.findtext("value") or "") for d in x.findall(".//jobDescription"))
        raw = {child.tag: child.text for child in x if len(child) == 0}
        c.add(job(c.source, ident, x.findtext("name"), description=desc,
            url=f"{c.source.origin}/job/{ident}", location=x.findtext("office"), raw=raw,
            posted_at=date_value(x.findtext("createdAt")), employment_type=x.findtext("employmentType")))
    c.finish(True)


async def amazon(c):
    params = {"result_limit": 100, "sort": "recent"}
    for key in ("base_query", "loc_query", "normalized_country_code[]", "category[]"):
        if c.source.config.get(key):
            params[key] = c.source.config[key]
            c.scope = "query"
    start = cursor_at(c.source, "listing_cursor") // 100
    if start:
        c.scope = "query"
    c.next_listing_cursor = start * 100
    for page in range(start, start + c.max_pages):
        data = await c.http.json("GET", "https://www.amazon.jobs/en/search.json", params={**params, "offset": page * 100}, headers={"Accept-Encoding": "identity"})
        items = rows_at(data, "jobs")
        reported = reported_count(data.get("hits"))
        if c.reported_total is not None and reported != c.reported_total:
            c.problem("inventory_changed_during_scan")
        c.reported_total = reported
        new = 0
        for x in items:
            desc = "\n".join(x.get(k) or "" for k in ("description", "basic_qualifications", "preferred_qualifications"))
            new += c.add(job(c.source, x.get("id_icims") or x.get("id"), x.get("title"), description=desc,
                url=urljoin("https://www.amazon.jobs", x.get("job_path") or ""), location=x.get("location"), raw=x,
                requisition_id=str(x.get("id_icims")) if x.get("id_icims") else None,
                country=x.get("country_code"), posted_at=date_value(x.get("posted_date")),
                employment_type="internship" if x.get("is_intern") is True else x.get("job_schedule_type")))
        c.next_listing_cursor = (page + 1) * 100
        if items and not new:
            raise SourceError("pagination_repeated_page")
        if c.reported_total is not None and page * 100 + len(items) >= c.reported_total:
            c.next_listing_cursor = 0
            inventory_finished(c, start == 0 and len(c.jobs) >= c.reported_total)
            c.finish(True); return
        if len(items) < 100:
            c.next_listing_cursor = 0
            inventory_finished(c, start == 0 and c.reported_total is None)
            c.finish(c.reported_total is None); return
    c.problem("page_limit_reached")


async def breezy(c):
    data = await c.http.json("GET", c.source.origin + "/json")
    if not isinstance(data, list):
        raise SchemaError("expected_breezy_array")
    def parse(x, desc=None):
        url = x.get("url") or c.source.origin + "/p/" + str(x.get("id") or x.get("_id"))
        return job(c.source, x.get("id") or x.get("_id"), x.get("name"), description=desc or x.get("description"),
            url=url, location=x.get("location"), raw=x, employment_type=x.get("type"),
            posted_at=date_value(x.get("published_date")))
    for x in data:
        c.add(parse(x))
    listing_complete = len(c.jobs) == len(data)
    inventory_finished(c, listing_complete)
    async def enrich(x):
        url = x.get("url") or c.source.origin + "/p/" + str(x.get("id") or x.get("_id"))
        html = await c.detail_text(url)
        details = parse_jsonld(c.source, html or "", url)
        if html is not None and not details:
            c.problem("detail_jobposting_unavailable")
        return parse(x, details[0]["description_html"] if details else None)
    await rotating_details(c, [x for x in data if not x.get("description")], enrich)
    c.finish(listing_complete)


async def pinpoint(c):
    records = []
    listing_complete = False
    next_url = c.source.origin + "/postings.json"
    visited = set()
    def parse(x, fetched=None):
        a = x.get("attributes") or x
        description = fetched or a.get("description") or a.get("description_html") or a.get("job_description")
        if description:
            description += "\n" + "\n".join(a.get(k) or "" for k in ("key_responsibilities", "skills_knowledge_expertise", "benefits"))
        url = a.get("url") or a.get("job_url") or f"{c.source.origin}/postings/{x.get('id')}"
        return job(c.source, x.get("id"), a.get("title"), description=description, url=url,
                  location=a.get("location") or a.get("location_name"), raw=x,
                  posted_at=date_value(a.get("published_at")), deadline=date_value(a.get("deadline_at")),
                  employment_type=a.get("employment_type_text") or a.get("employment_type"),
                  work_mode=a.get("workplace_type_text") or a.get("workplace_type") or "unknown",
                  compensation=compensation(a.get("compensation_minimum"), a.get("compensation_maximum"), a.get("compensation_currency"), a.get("compensation_frequency"), a.get("compensation")))
    for _ in range(c.max_pages):
        if next_url in visited:
            c.problem("pagination_repeated_page")
            break
        visited.add(next_url)
        data = await c.http.json("GET", next_url)
        items = rows_at(data, "data")
        new = 0
        for x in items:
            accepted = c.add(parse(x))
            new += accepted
            if accepted:
                records.append(x)
        if items and not new:
            c.problem("pagination_repeated_page")
            break
        target = (data.get("links") or {}).get("next")
        if not target:
            listing_complete = True
            break
        if not isinstance(target, str):
            raise SchemaError("invalid_pagination_next_link")
        candidate = urljoin(next_url, target)
        if urlsplit(candidate).netloc != urlsplit(c.source.origin).netloc:
            raise SourceError("unsafe_pagination_next_origin")
        next_url = candidate
    else:
        c.problem("page_limit_reached")
    inventory_finished(c, listing_complete)
    async def enrich(x):
        item = parse(x)
        html = await c.detail_text(item["canonical_url"])
        details = parse_jsonld(c.source, html or "", item["canonical_url"])
        if html is not None and not details:
            c.problem("detail_jobposting_unavailable")
        return parse(x, details[0]["description_html"] if details else None)
    await rotating_details(c, [x for x in records if not parse(x)["description"]], enrich)
    c.finish(listing_complete)


async def bamboohr(c):
    data = await c.http.json("GET", c.source.origin + "/careers/list")
    items = rows_at(data, "result")
    def parse(x, detail=None):
        ident = x.get("id")
        d = (detail or {}).get("result") or detail or x
        if isinstance(d, dict):
            d = d.get("jobOpening") or d
        if isinstance(d, list):
            d = d[0] if d else x
        return job(c.source, ident, x.get("jobOpeningName") or x.get("title"),
            description=d.get("description") or d.get("jobDescription"), url=c.source.origin + f"/careers/{ident}",
            location=x.get("location"), raw={"listing": x, "detail": d},
            employment_type=x.get("employmentStatusLabel"))
    for x in items:
        c.add(parse(x))
    listing_complete = len(c.jobs) == len(items)
    inventory_finished(c, listing_complete)
    async def enrich(x):
        detail = await c.detail_json(c.source.origin + f"/careers/{x.get('id')}/detail")
        return parse(x, detail)
    await rotating_details(c, [x for x in items if not parse(x)["description"]], enrich)
    c.finish(listing_complete)


async def generic(c):
    """JSON-LD details + bounded linked detail discovery; no false full scan."""
    c.scope = "discovery"
    if c.source.config.get('api_url'):
        await configured_public_api(c);return
    html = await c.http.text(c.source.url)
    direct = parse_jsonld(c.source, html, c.source.url)
    for item in direct:
        c.add(item)
    if direct:
        c.finish(True); return
    links = []
    for item in jsonld_objects(html):
        if item.get("@type") == "ItemList":
            for element in item.get("itemListElement", []):
                target = element.get("url") or element.get("item")
                if isinstance(target, dict):
                    target = target.get("url") or target.get("@id")
                if isinstance(target, str):
                    links.append(urljoin(c.source.url, target))
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        target = urljoin(c.source.url, anchor["href"])
        path=urlsplit(target).path
        if (urlsplit(target).hostname or '').endswith('google.com') and '/jobs/results/' in path and not re.search(r'/jobs/results/\d+',path):continue
        if urlsplit(target).netloc == urlsplit(c.source.url).netloc and re.search(r"/(?:job|jobs|careers|internship)/(?:detail/)?[^/?]+", path):
            links.append(target)
    links = list(dict.fromkeys(links))
    offset=int(c.source.config.get("detail_cursor",0)) % max(1,len(links))
    selected=links[offset:offset+c.max_details]
    c.next_detail_cursor=offset+len(selected) if offset+len(selected)<len(links) else 0
    c.scope="discovery"
    for link in selected:
        text = await c.detail_text(link)
        for item in parse_jsonld(c.source, text or "", link):
            c.add(item)
    if not c.jobs and len(links)>c.max_details:
        c.problem("detail_limit_reached");c.finish(False);return
    if not c.jobs:
        raise SourceError("no_public_jobposting_data; manual_capture_available")
    if len(links) > c.max_details:
        c.problem("detail_limit_reached")
    c.finish(True)


def feed_field(data, specification):
    """Interpret a small declared field grammar; never execute registry expressions."""
    if isinstance(specification, dict):
        if "path" in specification:
            value = feed_field(data, specification["path"])
            mapping = specification.get("map")
            return mapping.get(str(value), value) if isinstance(mapping, dict) else value
        if "concat" in specification:
            parts = []
            for part in specification["concat"]:
                if isinstance(part, str):
                    value = feed_field(data, part)
                    if value is not None:
                        parts.append(str(value))
                elif isinstance(part, dict) and part.get("each"):
                    values = feed_field(data, part["each"]) or []
                    if not isinstance(values, list):
                        raise SchemaError("configured_feed_expected_each_array")
                    template = str(part.get("wrap") or "{content}")
                    for value in values:
                        if isinstance(value, dict):
                            parts.append(re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}",
                                lambda match: str(value.get(match.group(1)) or ""), template))
                else:
                    raise SchemaError("configured_feed_unsupported_concat")
            return str(specification.get("separator") or "\n").join(parts)
        raise SchemaError("configured_feed_unsupported_field_specification")
    if not isinstance(specification, str):
        raise SchemaError("configured_feed_field_requires_path")
    alternatives = specification.split("||")
    last_value = None
    for alternative in alternatives:
        tokens = alternative.strip().split(".") if alternative.strip() else []
        def walk(value, index):
            if index == len(tokens):
                return value
            token = re.fullmatch(r"([A-Za-z_$][A-Za-z0-9_$-]*)(?:\[(\d+|\*)?\])?", tokens[index])
            if not token:
                raise SchemaError("configured_feed_unsupported_path")
            if not isinstance(value, dict):
                return None
            child = value.get(token.group(1))
            if "[" in tokens[index]:
                if not isinstance(child, list):
                    return None
                selector = token.group(2)
                if selector and selector.isdigit():
                    position = int(selector)
                    return walk(child[position], index + 1) if position < len(child) else None
                results = [walk(item, index + 1) for item in child]
                return [item for item in results if item is not None]
            return walk(child, index + 1)
        result = walk(data, 0)
        if result is not None:
            last_value = result
        if result is not None and result != "" and result != []:
            return result
    return last_value


def feed_set_parameter(data, path, value):
    """Set a declared scalar parameter, including a JSON object in a form value."""
    keys = str(path).split(".")
    if not keys or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key) for key in keys):
        raise SchemaError("configured_feed_invalid_pagination_parameter")
    def set_value(container, index):
        encoded = isinstance(container, str)
        if encoded:
            try:
                container = json.loads(container)
            except ValueError as exc:
                raise SchemaError("configured_feed_pagination_body_not_json") from exc
        if not isinstance(container, dict):
            raise SchemaError("configured_feed_pagination_requires_object")
        key = keys[index]
        if index + 1 == len(keys):
            container[key] = value
        else:
            container[key] = set_value(container.get(key, {}), index + 1)
        return json.dumps(container) if encoded else container
    return set_value(data, 0)


def feed_page_size(config, body, params):
    declared = (config.get("pagination") or {}).get("page_size")
    if declared:
        return int(declared)
    size_keys = {"limit", "pageSize", "page_size", "pagesize", "result_limit", "maxResults", "numberOfRecordsPerPage"}
    def search(value):
        if isinstance(value, str) and value.startswith("{"):
            try:
                value = json.loads(value)
            except ValueError:
                return None
        if not isinstance(value, dict):
            return None
        for key, item in value.items():
            if key in size_keys:
                try:
                    size = int(item)
                except (TypeError, ValueError):
                    continue
                if size > 0:
                    return size
        return next((size for item in value.values() if (size := search(item))), None)
    return search(body) or search(params)


async def configured_public_api(c):
    """Read explicitly declared public search requests and their bounded pages."""
    config = c.source.config
    if config.get("api_url") == "https://a.sfdcstatic.com/digital/xsf/careers/prod/jobs_2.json":
        # Salesforce publishes one static JSON inventory with all full JDs.
        # Verified 7 October: 1,517 identities, 9,836,365 decoded bytes (2.38 MB
        # gzipped). Only this exact official asset receives a 16 MB ceiling;
        # arbitrary configured feeds keep their normal transport limit.
        c.http.max_bytes = max(c.http.max_bytes, 16_000_000)
    method = str(config.get("method", "GET")).upper()
    if method not in {"GET", "POST"}:
        raise SchemaError("configured_feed_requires_read_method")
    headers = config.get("request_headers") or {}
    if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
        raise SchemaError("configured_feed_invalid_headers")
    content_type = next((value for key, value in headers.items() if key.lower() == "content-type"), "application/json")
    params = dict(config.get("params") or {})
    body = config.get("post_data")
    if method == "POST":
        if "application/x-www-form-urlencoded" in content_type:
            if isinstance(body, str):
                body = {key: values[-1] for key, values in parse_qs(body, keep_blank_values=True).items()}
            elif body is None:
                body, params = params, {}
        elif isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError as exc:
                raise SchemaError("configured_feed_invalid_json_body") from exc
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise SchemaError("configured_feed_body_requires_object")
        if isinstance(body.get("query"), str):
            query = body["query"].replace("\\n", "\n")
            if re.search(r"\b(?:mutation|subscription)\b", query, re.I):
                raise SourceError("configured_feed_graphql_write_operation_rejected")
            body = {**body, "query": query}
    mapping = config.get("fields") or {}
    if not isinstance(mapping, dict):
        raise SchemaError("configured_feed_fields_require_object")
    pagination = config.get("pagination") or {}
    initial = int(pagination.get("start_value", 0))
    increment = int(pagination.get("increment", 1))
    if increment <= 0 or initial < 0:
        raise SchemaError("configured_feed_invalid_pagination_increment")
    page_start = cursor_at(c.source, "listing_cursor") if pagination else 0
    page_size = feed_page_size(config, body, params)
    listing_complete = False
    c.scope = "discovery"
    if page_start:
        c.warnings.append("continued_listing_segment; full_inventory_not_proven")
    c.next_listing_cursor = page_start
    for page in range(page_start, page_start + (c.max_pages if pagination else 1)):
        request_body = json.loads(json.dumps(body)) if body is not None else None
        request_params = dict(params)
        if pagination:
            location = pagination.get("location", "query")
            parameter = pagination.get("param_name")
            value = initial + page * increment
            if location == "body" and method == "POST":
                request_body = feed_set_parameter(request_body, parameter, value)
            elif location in {"query", "params", "url"}:
                request_params = feed_set_parameter(request_params, parameter, value)
            else:
                raise SchemaError("configured_feed_unsupported_pagination_location")
        kwargs = {"params": request_params, "headers": headers}
        if method == "POST":
            kwargs["data" if "application/x-www-form-urlencoded" in content_type else "json"] = request_body
        payload = await c.http.json(method, config["api_url"], **kwargs)
        records = feed_field(payload, config["json_path"]) if config.get("json_path") else payload
        if not isinstance(records, list):
            raise SchemaError("configured_feed_expected_array")
        # An explicit response count is necessary to reject truncated short pages.
        total = feed_field(payload, config["total_path"]) if config.get("total_path") else None
        if total is not None:
            if isinstance(total, bool) or not str(total).isdigit():
                raise SchemaError("configured_feed_invalid_total")
            total = int(total)
            if c.reported_total is not None and total != c.reported_total:
                c.problem("inventory_changed_during_scan")
            c.reported_total = total
        new = 0
        for record in records:
            if not isinstance(record, dict):
                raise SchemaError("configured_feed_expected_record")
            values = {name: feed_field(record, specification) for name, specification in mapping.items()}
            ident = values.get("metadata.ats_job_id") or values.get("id") or record.get("id")
            title = values.get("title")
            url = values.get("url") or values.get("apply_url") or values.get("metadata.apply_url")
            if config.get("url_field"):
                url = feed_field(record, config["url_field"]) or url
            if config.get("url_template"):
                terms = {key: quote(str(value), safe="") for key, value in record.items() if isinstance(value, (str, int, float))}
                if "slug_fields" in config:
                    terms["slug"] = "-".join(re.sub(r"[^a-z0-9]+", " ", plain(" ".join(str(record.get(k) or "") for k in config["slug_fields"])).lower()).split())
                try:
                    url = config["url_template"].format(**terms)
                except KeyError as exc:
                    raise SchemaError("configured_feed_missing_url_field") from exc
            transform = config.get("url_transform") or {}
            if url and transform.get("find"):
                url = re.sub(transform["find"], str(transform.get("replace", "")), str(url))
            if config.get("url_filter") and url and not re.search(config["url_filter"], str(url)):
                continue
            if not title or not url:
                raise SchemaError("configured_feed_missing_title_or_url")
            description = "" if config.get("description_is_partial") else values.get("description") or ""
            new += c.add(job(c.source, ident or url, title, description=description, url=url,
                location=values.get("locations") or values.get("location") or "", employment_type=values.get("employment_type"),
                posted_at=date_value(values.get("date_posted")), raw=record))
        c.next_listing_cursor = page + 1
        if records and not new:
            c.problem("pagination_repeated_page_or_unrecognized_records")
            break
        if total is not None and page_start == 0 and len(c.jobs) >= total:
            listing_complete = "inventory_changed_during_scan" not in c.errors
            c.next_listing_cursor = 0
            break
        terminal = not records or (page_size is not None and len(records) < page_size) or not pagination
        if terminal:
            listing_complete = page_start == 0 and (total is None or len(c.jobs) >= total) and "inventory_changed_during_scan" not in c.errors
            c.next_listing_cursor = 0
            break
    else:
        c.problem("page_limit_reached")
    if config.get("inventory_unproven"):
        listing_complete = False
        c.warnings.append("configured_feed_inventory_unproven")
    if config.get("description_is_partial"):
        c.warnings.append("summary_only_description; full_job_detail_refresh_required")
    inventory_finished(c, listing_complete)
    c.finish(listing_complete)

def parse_internshala(source, html, page_url):
    """Keep employer and role within the same card; never zip unrelated labels."""
    is_detail = '/internship/detail/' in urlsplit(page_url).path
    soup = BeautifulSoup(html, 'html.parser')
    canonical_node = soup.select_one('link[rel="canonical"][href]') if is_detail else None
    detail_url = urljoin(page_url, canonical_node['href']) if canonical_node else page_url
    # Related internships have the same card classes as the primary role. The
    # observed detail_view contains the primary header and description only.
    detail_view = soup.select_one('#details_container .detail_view, .detail_view') if is_detail else None
    primary_card = detail_view.select_one('.individual_internship') if detail_view else None
    def internship_id(card):
        if card is None:
            return None
        value = card.get('internshipid')
        match = re.fullmatch(r'individual_internship_(\d+)', str(card.get('id') or ''))
        return str(value) if value else match.group(1) if match else None
    structured = parse_jsonld(source, html, detail_url)
    if structured:
        if is_detail:
            for item in structured:
                item['raw'] = {'jobposting': item.get('raw'),
                    'internship_id': internship_id(primary_card),
                    'page_url': page_url, 'page_canonical': detail_url,
                    'parser': 'internshala-detail-jsonld-v3'}
        return structured
    cards = soup.select('.individual_internship')
    if is_detail:
        # Do not infer the main role from the first recommended-card anchor.
        # An unknown detail layout remains unsupported instead of mixing jobs.
        if detail_view is None or detail_view.select_one('.internship_details') is None:
            return []
        cards = [primary_card or detail_view]
    results = []
    for card in cards:
        title = card.select_one('.job-internship-name, .job-title-href, .job-title, .profile, h1')
        employer = card.select_one('.company-name') or card.select_one('.company_name')
        anchor = card.select_one('a[href*="/internship/detail/"]') if not is_detail else None
        url = detail_url if is_detail else urljoin(page_url, anchor['href']) if anchor else page_url
        if not title or not employer or '/internship/detail/' not in urlsplit(url).path:
            continue
        location_node = card.select_one('.locations') or card.select_one('.location_link') or card.select_one('#location_names')
        location = location_node.get_text(' ', strip=True) if location_node else ''
        if re.fullmatch(r'work\s*from\s*home', location, re.I):
            location = 'Remote, India'
        if not location:
            path = urlsplit(url).path
            if 'work-from-home' in path: location = 'Remote, India'
            elif 'internship-in-chennai-at-' in path: location = 'Chennai, India'
            elif any('internship-in-'+city+'-at-' in path for city in ('bangalore','bengaluru')): location = 'Bengaluru, India'
        detail = detail_view.select_one('.internship_details') if is_detail else None
        results.append(job(source, url, title.get_text(' ', strip=True), url=url,
            company_name=employer.get_text(' ', strip=True), location=location,
            employment_type='internship', description=detail.get_text(' ', strip=True) if detail else '',
            raw={'page_url':page_url,'internship_id':internship_id(card),
                 'page_canonical':detail_url if is_detail else None,
                 'parser':'internshala-scoped-card-v3'}))
    return results


async def internshala(c):
    c.scope = 'discovery'
    start = cursor_at(c.source, 'listing_cursor')
    c.next_listing_cursor = start
    page_url = c.source.url
    html = await c.http.text(page_url)
    initial_html, initial_url = html, page_url
    def next_link(text, current):
        soup = BeautifulSoup(text, 'html.parser')
        anchor = soup.select_one('a.next_page[href], a#navigation-forward[href], a[rel="next"][href]')
        if anchor is None or 'disabled' in (anchor.get('class') or []) or anchor.get('aria-disabled') == 'true':
            return None
        href = anchor.get('href')
        if not href or href == '#':
            return None
        target = urljoin(current, href)
        parsed = urlsplit(target)
        if parsed.scheme not in {'http', 'https'} or parsed.netloc != urlsplit(c.source.url).netloc:
            raise SourceError('unsafe_pagination_next_origin')
        return target
    if start:
        observed = next_link(html, page_url)
        if observed is None:
            # Reset a stale checkpoint, then let a new zero-offset pass prove it.
            c.next_listing_cursor = 0
            c.warnings.append('listing_cursor_reset; fresh_inventory_pass_required')
        elif re.search(r'/page-\d+/?(?:\?|$)', observed):
            page_url = re.sub(r'/page-\d+(?=/|\?|$)', f'/page-{start + 1}', observed)
            html = await c.http.text(page_url)
            c.warnings.append('continued_listing_segment; full_inventory_not_proven')
        else:
            c.problem('listing_cursor_resume_unavailable')
            c.next_listing_cursor = 0
    visited = set()
    listing_complete = False
    for page in range(start, start + c.max_pages):
        if page_url in visited:
            c.problem('pagination_repeated_page')
            break
        visited.add(page_url)
        items = parse_internshala(c.source, html, page_url)
        new = sum(c.add(item) for item in items)
        if not items:
            terminal = BeautifulSoup(html, 'html.parser')
            empty_terminal = bool(terminal.select_one('input#isLastPage[value="1"]')
                and terminal.select_one('#individual_location_end_result .end_result_container'))
            if empty_terminal:
                # Public pagination explicitly ends this location scope. SEO
                # headline counts include other suggestions and are not an
                # inventory total. A resumed terminal page still needs a new
                # zero-offset pass before the query can claim completeness.
                if start:
                    for item in parse_internshala(c.source, initial_html, initial_url):
                        c.add(item)
                    c.warnings.append('empty_terminal_checkpoint_reset; fresh_inventory_pass_required')
                c.next_listing_cursor = 0
                listing_complete = start == 0
                break
            # A saved cursor can lead to an unrendered second page even while
            # the current category head supplies valid public cards. Retain
            # those leads and reset the checkpoint; never claim an empty or
            # complete inventory from this unsupported pagination response.
            head_items = parse_internshala(c.source, initial_html, initial_url)
            if head_items and page_url != initial_url:
                for item in head_items:
                    c.add(item)
                c.next_listing_cursor = 0
                c.problem(f'internshala_pagination_page_unrecognized: page_url={page_url}, checkpoint_reset=0')
                break
            raise SchemaError('internshala_no_recognized_cards_or_jobposting; manual_capture_available')
        if not new:
            c.problem('pagination_repeated_page')
            break
        target = next_link(html, page_url)
        if not target:
            c.next_listing_cursor = 0
            listing_complete = start == 0
            break
        if target in visited:
            c.problem('pagination_repeated_page')
            break
        c.next_listing_cursor = page + 1
        if page + 1 < start + c.max_pages:
            page_url = target
            html = await c.http.text(page_url)
    else:
        c.problem('page_limit_reached')
    inventory_finished(c, listing_complete)
    targets = [item for item in c.jobs.values() if detail_candidate(item)]
    c.description_target_count = len(targets)
    c.description_scope = 'target_candidates' if c.max_details else 'listing_only'
    if not c.max_details:
        c.description_complete = all(bool(item.get('description')) for item in targets)
        if not c.description_complete:
            c.warnings.append('listing_only; candidate_job_descriptions_not_requested')
        c.next_detail_cursor = 0
        c.finish(listing_complete)
        return
    c.source.config = {**c.source.config, 'detail_target_only': True}
    from ..domain import canonicalize_url
    def employer_key(value):
        return re.sub(r'[^a-z0-9]+', '', plain(value).casefold())
    def record_id(item):
        raw = item.get('raw') or {}
        if isinstance(raw, dict) and isinstance(raw.get('source_payload'), dict):
            raw = raw['source_payload']
        return str(raw.get('internship_id')) if isinstance(raw, dict) and raw.get('internship_id') else None
    def page_canonical(item):
        raw = item.get('raw') or {}
        if isinstance(raw, dict) and isinstance(raw.get('source_payload'), dict):
            raw = raw['source_payload']
        return raw.get('page_canonical') if isinstance(raw, dict) else None
    async def enrich(listing):
        target_url = listing['canonical_url']
        c.detail_requests += 1
        try:
            response = await c.http.request('GET', target_url)
        except SourceError as exc:
            c.problem('detail_fetch_failed: ' + str(exc))
            return None
        if canonicalize_url(str(response.url)) != canonicalize_url(target_url):
            c.problem(f'internshala_detail_identity_mismatch: redirected_url, job_url={target_url}, final_url={response.url}')
            return None
        details = parse_internshala(c.source, response.text, target_url)
        same_url = [item for item in details
            if canonicalize_url(item.get('canonical_url')) == canonicalize_url(target_url)
            and (not page_canonical(item) or canonicalize_url(page_canonical(item)) == canonicalize_url(target_url))]
        same_employer = [item for item in same_url if employer_key(item.get('company_name')) == employer_key(listing.get('company_name'))]
        candidates = [item for item in same_employer if not record_id(listing) or not record_id(item) or record_id(listing) == record_id(item)]
        if not candidates:
            component = 'canonical_url' if not same_url else 'employer' if not same_employer else 'internship_id'
            c.problem(f'internshala_detail_identity_mismatch: {component}, job_url={target_url}' if details else f'full_description_unavailable: job_url={target_url}')
            return None
        detail = candidates[0]
        if not detail.get('description'):
            c.problem('full_description_unavailable')
            return None
        # JSON-LD has a native identifier distinct from the listing URL. Never
        # create a second appearance or let related jobs rebind this employer.
        return {**listing, **detail, 'external_id': listing['external_id'],
            'title': listing['title'], 'canonical_url': target_url,
            'apply_url': listing['apply_url'], 'company_name': listing['company_name'],
            'raw': {'listing': listing.get('raw'), 'detail': detail.get('raw'),
                    'detail_external_id': detail.get('external_id'), 'detail_url': target_url},
            'evidence': list(listing.get('evidence') or []) + list(detail.get('evidence') or [])}
    missing = [item for item in c.jobs.values() if not item.get('description')]
    await rotating_details(c, missing, enrich)
    c.description_complete = all(bool(c.jobs[item['external_id']].get('description')) for item in targets)
    c.finish(listing_complete)


ADAPTERS = {
    "greenhouse": greenhouse, "lever": lever, "ashby": ashby,
    "smartrecruiters": smartrecruiters, "workday": workday, "oracle": oracle,
    "oracle_hcm": oracle, "eightfold": eightfold, "workable": workable,
    "recruitee": recruitee, "personio": personio, "amazon": amazon,
    "breezy": breezy, "pinpoint": pinpoint, "bamboohr": bamboohr,
    "generic": generic, "jsonld": generic, "html": generic,
    "internshala": internshala,
}
