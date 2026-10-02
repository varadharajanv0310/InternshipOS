"""Refresh saved IDs directly. Absence and 404 remain uncertain, never closure."""
from __future__ import annotations

from urllib.parse import quote, urlsplit

from .adapters import ashby, recruitee, slug, workday_target
from .parsing import compensation, date_value, job, parse_jsonld
from .types import SourceError


async def targeted_refresh(c):
    c.scope = "targeted"
    records = c.source.config.get("refresh_jobs") or [{"external_id": x} for x in c.source.config.get("refresh_external_ids", [])]
    ids = {str(x["external_id"]) for x in records if x.get("external_id") is not None}
    if not ids:
        raise SourceError("refresh_requires_external_ids")
    provider = c.source.provider
    # These APIs deliver all full descriptions in one inexpensive response.
    if provider in {"ashby", "recruitee"}:
        await {"ashby": ashby, "recruitee": recruitee}[provider](c)
        c.jobs = {key: value for key, value in c.jobs.items() if key in ids}
        missing = ids - c.jobs.keys()
        if missing:
            c.problem(f"saved_ids_not_in_current_feed:{len(missing)}; availability_uncertain")
        c.scope = "targeted"
        return
    for target in records[:50]:
        external_id = str(target.get("external_id") or "")
        url = target.get("canonical_url") or target.get("apply_url")
        try:
            if provider == "workday":
                origin, tenant, site = workday_target(c.source)
                api = f"{origin}/wday/cxs/{quote(tenant, safe='')}/{quote(site, safe='')}"
                path = urlsplit(url or "").path
                path = "/job/" + path.split("/job/", 1)[1] if "/job/" in path else None
                if not path:
                    listing = await c.http.json("POST", api + "/jobs", json={"limit": 20, "offset": 0, "searchText": external_id, "appliedFacets": {}})
                    matches = [x for x in listing.get("jobPostings", []) if external_id in x.get("bulletFields", [])]
                    path = matches[0].get("externalPath") if len(matches) == 1 else None
                if not path:
                    raise SourceError("saved_workday_path_unresolved")
                payload = await c.http.json("GET", api + path)
                d = payload.get("jobPostingInfo") or {}
                if not d.get("title") or not d.get("jobDescription"):
                    raise SourceError("saved_workday_detail_missing")
                value = job(c.source, external_id, d["title"], description=d["jobDescription"],
                    url=f"{origin}/{site}{path}", location=[d.get("location")] + (d.get("additionalLocations") or []),
                    requisition_id=d.get("jobReqId") or target.get("requisition_id"),
                    posted_at=date_value(d.get("startDate")), deadline=date_value(d.get("endDate")),
                    employment_type=d.get("timeType"), work_mode=d.get("remoteType") or "unknown", raw=payload)
            elif provider == "greenhouse":
                token = slug(c.source)
                d = await c.http.json("GET", f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{quote(external_id, safe='')}")
                value = job(c.source, external_id, d.get("title"), description=d.get("content"), url=d.get("absolute_url") or url,
                    location=d.get("location"), requisition_id=d.get("requisition_id") or target.get("requisition_id"), raw=d,
                    deadline=date_value(d.get("application_deadline")), posted_at=date_value(d.get("first_published")))
            elif provider in {"oracle", "oracle_hcm"}:
                d = await c.http.json("GET", c.source.origin + "/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails",
                                      params={"finder": f"ById;Id={external_id}", "onlyData": "true"})
                items = d.get("items") or []
                if not items:
                    raise SourceError("saved_oracle_detail_missing")
                x = items[0]
                if not x.get("ExternalDescriptionStr"):
                    raise SourceError("saved_oracle_full_description_missing")
                description = "\n".join(x.get(k) or "" for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"))
                value = job(c.source, external_id, x.get("Title") or target.get("title"), description=description, url=url,
                    location=x.get("PrimaryLocation"), country=x.get("PrimaryLocationCountry"), raw=d,
                    deadline=date_value(x.get("PostingEndDate")), requisition_id=target.get("requisition_id"))
            elif provider == "eightfold":
                d = await c.http.json("GET", c.source.origin + "/api/pcsx/position_details", params={"position_id": external_id,
                    "domain": c.source.config.get("domain") or c.source.company_domain, "hl": "en"})
                x = d.get("data") or {}
                value = job(c.source, external_id, x.get("name") or x.get("title") or x.get("jobTitle") or target.get("title"),
                    description=x.get("jobDescription"), url=url or f"{c.source.origin}/careers/job/{external_id}",
                    location=x.get("locations"), raw=d, requisition_id=x.get("atsJobId") or target.get("requisition_id"))
            elif provider == "smartrecruiters":
                token = slug(c.source)
                x = await c.http.json("GET", f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{quote(external_id, safe='')}")
                sections = (x.get("jobAd") or {}).get("sections") or {}
                description = "\n".join(v.get("text", "") for v in sections.values() if isinstance(v, dict))
                value = job(c.source, external_id, x.get("name"), description=description, url=x.get("postingUrl") or url,
                    apply_url=x.get("applyUrl") or url, location=x.get("location"), raw=x)
            elif provider == "freehire":
                payload = await c.http.json("GET", "https://freehire.me/api/v1/jobs/" + quote(external_id, safe=""))
                x = payload.get("data") or {}
                if x.get("closed_at"):
                    raise SourceError("aggregator_reports_closed; canonical_confirmation_needed")
                value = job(c.source, external_id, x.get("title"), description=x.get("description"),
                    url=x.get("url"), location=x.get("location"), company_name=x.get("company"), company_domain=None, raw=x)
            else:
                if not url:
                    raise SourceError("saved_job_url_required_for_detail_refresh")
                html = await c.http.text(url)
                matches = parse_jsonld(c.source, html, url)
                if len(matches) != 1:
                    raise SourceError("saved_detail_not_unambiguous_jsonld; availability_uncertain")
                value = matches[0]
                value["external_id"] = external_id
                value["requisition_id"] = target.get("requisition_id") or value.get("requisition_id")
            if not value.get("title") or not value.get("description"):
                raise SourceError("saved_detail_incomplete")
            if target.get("company_name"):
                value["company_name"] = target["company_name"]
                value["company_domain"] = target.get("company_domain")
            value["raw"] = {"detail": value["raw"], "targeted_refresh": True,
                            "opportunity_id": target.get("opportunity_id")}
            c.add(value)
        except SourceError as exc:
            c.problem(f"saved_detail_fetch_error:{external_id}:{exc}")
    if len(records) > 50:
        c.problem("saved_refresh_limit_reached")
    c.finish(len(c.jobs) == len(ids))
    c.scope = "targeted"
