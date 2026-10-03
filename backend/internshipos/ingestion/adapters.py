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
    payload = await c.http.json("GET", f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"})
    items = rows_at(payload, "jobs")
    c.reported_total = payload.get("meta", {}).get("total", len(items))
    for x in items:
        pay = (x.get("pay_input_ranges") or [{}])[0]
        c.add(job(c.source, x.get("id"), x.get("title"), description=x.get("content"),
                  url=x.get("absolute_url"), location=x.get("location"), raw=x,
                  requisition_id=x.get("requisition_id"), posted_at=date_value(x.get("first_published")), deadline=date_value(x.get("application_deadline")),
                  compensation=compensation(pay.get("min_cents") / 100 if pay.get("min_cents") is not None else None,
                    pay.get("max_cents") / 100 if pay.get("max_cents") is not None else None, pay.get("currency_type"), "year" if pay else None)))
    c.finish(len(items) == c.reported_total)


async def lever(c):
    token = slug(c.source)
    host = "api.eu.lever.co" if "eu.lever.co" in c.source.url else "api.lever.co"
    for page in range(c.max_pages):
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
        if len(payload) < 100:
            c.finish(True)
            return
        if not new:
            raise SourceError("pagination_repeated_page")
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
    for page in range(c.max_pages):
        data = await c.http.json("GET", f"https://api.smartrecruiters.com/v1/companies/{token}/postings", params={"limit": 100, "offset": page * 100})
        items = rows_at(data, "content")
        c.reported_total = data.get("totalFound")
        new = 0
        for x in items:
            ident = x.get("id")
            detail = await c.detail_json(f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{quote(str(ident), safe='')}")
            d = detail or x
            sections = (d.get("jobAd") or {}).get("sections") or {}
            desc = "\n".join(v.get("text", "") for v in sections.values() if isinstance(v, dict))
            new += c.add(job(c.source, ident, d.get("name") or x.get("name"), description=desc,
                url=d.get("postingUrl") or f"https://jobs.smartrecruiters.com/{token}/{ident}",
                apply_url=d.get("applyUrl") or d.get("postingUrl") or f"https://jobs.smartrecruiters.com/{token}/{ident}",
                location=d.get("location"), raw=d, country=(d.get("location") or {}).get("country"),
                work_mode="remote" if (d.get("location") or {}).get("remote") is True else "unknown",
                posted_at=date_value(d.get("releasedDate")), employment_type=(d.get("typeOfEmployment") or {}).get("label")))
        if c.reported_total is not None and (page + 1) * 100 >= int(c.reported_total):
            c.finish(True); return
        if len(items) < 100:
            c.finish(c.reported_total is None or len(c.jobs) >= int(c.reported_total)); return
        if not new:
            raise SourceError("pagination_repeated_page")
    c.problem("page_limit_reached")


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
    cursor=max(0,int(c.source.config.get('detail_cursor',0)))
    start_page=cursor//20
    if cursor: c.scope='query'  # A continuation cannot prove full-board absence.
    for page in range(start_page,start_page+c.max_pages):
        data = await c.http.json("POST", f"{api}/jobs", json={"limit": 20, "offset": page * 20, "searchText": query, "appliedFacets": facets})
        items = rows_at(data, "jobPostings")
        total = data.get("total")
        if not isinstance(total, int):
            raise SchemaError("missing_workday_total")
        c.reported_total = total
        if cursor and cursor>=total:
            c.next_detail_cursor=0;c.problem('inventory_incomplete');c.finish(False);return
        if total >= 2000:
            c.problem("workday_query_cap_requires_partitioning")
        new = 0
        for index,x in enumerate(items):
            position=page*20+index
            if position<cursor:continue
            if c.max_details>0 and c.detail_requests>=c.max_details:
                c.next_detail_cursor=position;c.problem('detail_limit_reached');c.finish(False);return
            path = x.get("externalPath")
            if not path:
                c.problem("workday_missing_external_path"); continue
            detail = await c.detail_json(api + path)
            d = (detail or {}).get("jobPostingInfo") or {}
            locations = [d.get("location")] + (d.get("additionalLocations") or [])
            ident = d.get("jobReqId") or (x.get("bulletFields") or [None])[0] or path
            url = f"{origin}/{site}{path}"
            new += c.add(job(c.source, ident, d.get("title") or x.get("title"),
                description=d.get("jobDescription"), url=url, location=list(filter(None, locations)) or x.get("locationsText"),
                raw={"listing": x, "detail": detail}, requisition_id=d.get("jobReqId") or ident,
                posted_at=date_value(d.get("startDate")), deadline=date_value(d.get("endDate")),
                employment_type=d.get("timeType"), work_mode=d.get("remoteType") or "unknown"))
            c.next_detail_cursor=position+1
        if page * 20 + len(items) >= total:
            c.next_detail_cursor=0
            c.finish(total < 2000); return
        if not items or not new:
            raise SourceError("workday_pagination_incomplete_or_repeated")
    c.problem("page_limit_reached")


async def oracle(c):
    site_match = re.search(r"/sites/([^/?#]+)", c.source.url)
    site = c.source.config.get("site_number") or c.source.config.get("site") or (site_match.group(1) if site_match else "CX_1")
    api = c.source.origin + "/hcmRestApi/resources/latest/"
    cursor=max(0,int(c.source.config.get('detail_cursor',0)))
    if cursor:c.scope='query'
    for page in range(cursor//100,cursor//100+c.max_pages):
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
        c.reported_total = int(total) if total is not None else None
        new = 0
        for index,x in enumerate(items):
            position=page*100+index
            if position<cursor:continue
            if c.max_details>0 and c.detail_requests>=c.max_details:
                c.next_detail_cursor=position;c.problem('detail_limit_reached');c.finish(False);return
            ident = x.get("Id") or x.get("RequisitionNumber")
            response = await c.detail_json(api + "recruitingCEJobRequisitionDetails", params={"onlyData": "true", "finder": f"ById;Id={ident}"})
            detail_items = (response or {}).get("items") or []
            d = detail_items[0] if detail_items else x
            desc = "\n".join(d.get(k) or "" for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"))
            # Search snippets remain raw evidence; they must not overwrite a
            # saved full JD or advance the detail-refresh clock.
            if not d.get("ExternalDescriptionStr"):
                desc = ""
                c.problem("oracle_full_description_unavailable")
            url = f"{c.source.origin}/hcmUI/CandidateExperience/en/sites/{site}/job/{ident}"
            new += c.add(job(c.source, ident, x.get("Title"), description=desc, url=url,
                location=x.get("PrimaryLocation"), country=x.get("PrimaryLocationCountry"), raw={"listing": x, "detail": d},
                requisition_id=x.get("RequisitionNumber") or str(ident), posted_at=date_value(x.get("PostedDate")),
                deadline=date_value(x.get("PostingEndDate")), employment_type=x.get("JobType") or x.get("WorkerType"),
                work_mode={"ORA_REMOTE": "remote", "ORA_HYBRID": "hybrid", "ORA_ON_SITE": "onsite"}.get(x.get("WorkplaceTypeCode"), "unknown")))
            c.next_detail_cursor=position+1
        if c.reported_total is not None and page * 100 + len(items) >= c.reported_total:
            c.next_detail_cursor=0
            c.finish(True); return
        if not items:
            c.next_detail_cursor=0
            c.finish(c.reported_total is None or len(c.jobs) >= c.reported_total); return
        if not new:
            raise SourceError("pagination_repeated_page")
        if len(items) < 100 and c.reported_total is None:
            c.finish(True); return
    c.problem("page_limit_reached")


async def eightfold(c):
    domain = c.source.config.get("domain") or c.source.company_domain
    if not domain:
        raise SourceError("eightfold_company_domain_required")
    query = c.source.config.get("query", "")
    if query:
        c.scope = "query"
    start = max(0,int(c.source.config.get('detail_cursor',0)))
    if start:c.scope='query'
    for _ in range(c.max_pages):
        payload = await c.http.json("GET", c.source.origin + "/api/pcsx/search", params={"domain": domain, "query": query, "start": start, "sort_by": "timestamp"})
        data = payload.get("data") or {}
        items = rows_at(data, "positions")
        c.reported_total = int(data["count"]) if data.get("count") is not None else None
        new = 0
        for index,x in enumerate(items):
            if c.max_details>0 and c.detail_requests>=c.max_details:
                c.next_detail_cursor=start+index;c.problem('detail_limit_reached');c.finish(False);return
            ident = x.get("id")
            detail = await c.detail_json(c.source.origin + "/api/pcsx/position_details", params={"position_id": ident, "domain": domain, "hl": "en"})
            d = (detail or {}).get("data") or {}
            url = x.get("positionUrl") or f"{c.source.origin}/careers/job/{ident}"
            new += c.add(job(c.source, ident, x.get("name"), description=d.get("jobDescription") or x.get("job_description"),
                url=url, location=x.get("locations"), raw={"listing": x, "detail": d},
                requisition_id=x.get("atsJobId") or x.get("displayJobId"), posted_at=date_value(x.get("postedTs")),
                work_mode=x.get("workLocationOption") or "unknown"))
        start += len(items)
        c.next_detail_cursor=start
        if c.reported_total is not None and start >= c.reported_total:
            c.next_detail_cursor=0
            c.finish(True); return
        if not items:
            c.next_detail_cursor=0
            c.finish(c.reported_total is None or start >= c.reported_total); return
        if not new:
            raise SourceError("pagination_repeated_page")
    c.problem("page_limit_reached")


async def workable(c):
    token = slug(c.source)
    payload = await c.http.json("GET", f"https://apply.workable.com/api/v1/widget/accounts/{token}")
    for x in rows_at(payload, "jobs"):
        ident = x.get("shortcode") or x.get("id")
        desc = await c.detail_text(f"https://apply.workable.com/{token}/jobs/view/{ident}.md")
        c.add(job(c.source, ident, x.get("title"), description=desc or x.get("description"),
            url=x.get("url") or f"https://apply.workable.com/{token}/j/{ident}/", location=x.get("location"), raw=x,
            posted_at=date_value(x.get("published_on") or x.get("created_at")), employment_type=x.get("employment_type"),
            country=x.get("country"), work_mode="remote" if x.get("telecommuting") is True else "unknown"))
    c.finish(True)


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
    for page in range(c.max_pages):
        data = await c.http.json("GET", "https://www.amazon.jobs/en/search.json", params={**params, "offset": page * 100}, headers={"Accept-Encoding": "identity"})
        items = rows_at(data, "jobs")
        c.reported_total = int(data["hits"]) if data.get("hits") is not None else None
        new = 0
        for x in items:
            desc = "\n".join(x.get(k) or "" for k in ("description", "basic_qualifications", "preferred_qualifications"))
            new += c.add(job(c.source, x.get("id_icims") or x.get("id"), x.get("title"), description=desc,
                url=urljoin("https://www.amazon.jobs", x.get("job_path") or ""), location=x.get("location"), raw=x,
                requisition_id=str(x.get("id_icims")) if x.get("id_icims") else None,
                country=x.get("country_code"), posted_at=date_value(x.get("posted_date")),
                employment_type="internship" if x.get("is_intern") is True else x.get("job_schedule_type")))
        if c.reported_total is not None and page * 100 + len(items) >= c.reported_total:
            c.finish(True); return
        if len(items) < 100:
            c.finish(c.reported_total is None); return
        if not new:
            raise SourceError("pagination_repeated_page")
    c.problem("page_limit_reached")


async def breezy(c):
    data = await c.http.json("GET", c.source.origin + "/json")
    if not isinstance(data, list):
        raise SchemaError("expected_breezy_array")
    for x in data:
        url = x.get("url") or c.source.origin + "/p/" + str(x.get("id") or x.get("_id"))
        desc = x.get("description")
        if not desc:
            html = await c.detail_text(url)
            details = parse_jsonld(c.source, html or "", url)
            desc = details[0]["description_html"] if details else ""
        c.add(job(c.source, x.get("id") or x.get("_id"), x.get("name"), description=desc,
            url=url, location=x.get("location"), raw=x, employment_type=x.get("type"),
            posted_at=date_value(x.get("published_date"))))
    c.finish(True)


async def pinpoint(c):
    data = await c.http.json("GET", c.source.origin + "/postings.json")
    items = rows_at(data, "data")
    for x in items:
        a = x.get("attributes") or x
        description = a.get("description") or a.get("description_html") or a.get("job_description")
        if description:
            description += "\n" + "\n".join(a.get(k) or "" for k in ("key_responsibilities", "skills_knowledge_expertise", "benefits"))
        url = a.get("url") or a.get("job_url") or f"{c.source.origin}/postings/{x.get('id')}"
        if not description:
            html = await c.detail_text(url)
            details = parse_jsonld(c.source, html or "", url)
            description = details[0]["description_html"] if details else ""
        c.add(job(c.source, x.get("id"), a.get("title"), description=description, url=url,
                  location=a.get("location") or a.get("location_name"), raw=x,
                  posted_at=date_value(a.get("published_at")), deadline=date_value(a.get("deadline_at")),
                  employment_type=a.get("employment_type_text") or a.get("employment_type"),
                  work_mode=a.get("workplace_type_text") or a.get("workplace_type") or "unknown",
                  compensation=compensation(a.get("compensation_minimum"), a.get("compensation_maximum"), a.get("compensation_currency"), a.get("compensation_frequency"), a.get("compensation"))))
    # Some deployments paginate. A next link cannot be silently declared complete.
    c.finish(not (data.get("links") or {}).get("next"))


async def bamboohr(c):
    data = await c.http.json("GET", c.source.origin + "/careers/list")
    items = rows_at(data, "result")
    for x in items:
        ident = x.get("id")
        detail = await c.detail_json(c.source.origin + f"/careers/{ident}/detail")
        d = (detail or {}).get("result") or detail or x
        if isinstance(d, dict):
            d = d.get("jobOpening") or d
        if isinstance(d, list):
            d = d[0] if d else x
        c.add(job(c.source, ident, x.get("jobOpeningName") or x.get("title"),
            description=d.get("description") or d.get("jobDescription"), url=c.source.origin + f"/careers/{ident}",
            location=x.get("location"), raw={"listing": x, "detail": d},
            employment_type=x.get("employmentStatusLabel")))
    c.finish(True)


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


async def configured_public_api(c):
    """Use declared public feed fields without executing registry expressions."""
    config=c.source.config
    if config.get('method','GET').upper()!='GET':raise SchemaError('configured_feed_requires_get')
    payload=await c.http.json('GET',config['api_url'])
    def field(data,path):
        for key in str(path or '').split('.'):
            if not isinstance(data,dict):return None
            data=data.get(key)
        return data
    records=field(payload,config.get('json_path')) if config.get('json_path') else payload
    if not isinstance(records,list):raise SchemaError('configured_feed_expected_array')
    c.reported_total=field(payload,config.get('total_path')) if config.get('total_path') else len(records)
    mapping=config.get('fields') or {}
    for record in records:
        if not isinstance(record,dict):raise SchemaError('configured_feed_expected_record')
        values={name:field(record,path) for name,path in mapping.items() if isinstance(path,str)}
        ident=values.get('metadata.ats_job_id') or values.get('id') or record.get('id')
        title=values.get('title')
        url=values.get('url') or values.get('apply_url')
        if config.get('url_template'):
            terms={key:quote(str(value),safe='') for key,value in record.items() if isinstance(value,(str,int,float))}
            terms['slug']='-'.join(re.sub(r'[^a-z0-9]+',' ',plain(' '.join(str(record.get(k) or '') for k in config.get('slug_fields',[]))).lower()).split())
            try:url=config['url_template'].format(**terms)
            except KeyError as exc:raise SchemaError('configured_feed_missing_url_field') from exc
        if not title or not url:raise SchemaError('configured_feed_missing_title_or_url')
        c.add(job(c.source,ident or url,title,description=values.get('description') or '',url=url,
            location=values.get('locations') or values.get('location') or '',employment_type=values.get('employment_type'),
            posted_at=date_value(values.get('date_posted')),raw=record))
    if isinstance(c.reported_total,int) and c.reported_total>len(records):c.problem('inventory_incomplete')
    c.finish(True)


def parse_internshala(source, html, page_url):
    """Keep employer and role within the same card; never zip unrelated labels."""
    structured = parse_jsonld(source, html, page_url)
    if structured:
        return structured
    soup = BeautifulSoup(html, 'html.parser')
    cards = soup.select('.individual_internship')
    if '/internship/detail/' in urlsplit(page_url).path:
        cards = [soup]
    results = []
    for card in cards:
        title = card.select_one('.job-title, .profile, h1')
        employer = card.select_one('.company-name, .company_name')
        anchor = card.select_one('a[href*="/internship/detail/"]')
        url = urljoin(page_url, anchor['href']) if anchor else page_url
        if not title or not employer or '/internship/detail/' not in urlsplit(url).path:
            continue
        location_node = card.select_one('.location_link, .locations')
        location = location_node.get_text(' ', strip=True) if location_node else ''
        if not location:
            path = urlsplit(url).path
            if 'work-from-home' in path: location = 'Remote, India'
            elif 'internship-in-chennai-at-' in path: location = 'Chennai, India'
            elif any('internship-in-'+city+'-at-' in path for city in ('bangalore','bengaluru')): location = 'Bengaluru, India'
        detail = card.select_one('.internship_details') if '/internship/detail/' in urlsplit(page_url).path else None
        results.append(job(source, url, title.get_text(' ', strip=True), url=url,
            company_name=employer.get_text(' ', strip=True), location=location,
            employment_type='internship', description=detail.get_text(' ', strip=True) if detail else '',
            raw={'page_url':page_url,'parser':'internshala-scoped-card-v1'}))
    return results


async def internshala(c):
    c.scope = 'discovery'
    html = await c.http.text(c.source.url)
    for item in parse_internshala(c.source, html, c.source.url):
        c.add(item)
    if not c.jobs:
        raise SchemaError('internshala_no_recognized_cards_or_jobposting; manual_capture_available')
    c.finish(True)


ADAPTERS = {
    "greenhouse": greenhouse, "lever": lever, "ashby": ashby,
    "smartrecruiters": smartrecruiters, "workday": workday, "oracle": oracle,
    "oracle_hcm": oracle, "eightfold": eightfold, "workable": workable,
    "recruitee": recruitee, "personio": personio, "amazon": amazon,
    "breezy": breezy, "pinpoint": pinpoint, "bamboohr": bamboohr,
    "generic": generic, "jsonld": generic, "html": generic,
    "internshala": internshala,
}
