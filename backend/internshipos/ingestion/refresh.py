"""Refresh saved IDs directly. Absence and 404 remain uncertain, never closure."""
from __future__ import annotations

from urllib.parse import quote, urlsplit
import re

from .adapters import ashby, recruitee, slug, workday_target, workday_listing_identifiers, parse_internshala
from .parsing import compensation, date_value, job, parse_jsonld
from .types import SourceError


def _native_id(target,observed):
    if observed is None or str(observed)!=str(target.get('external_id')):
        raise SourceError('saved_detail_native_identity_mismatch')


def _same_host(target,value,provider):
    expected=urlsplit(target.get('canonical_url') or target.get('apply_url') or '').hostname
    actual=urlsplit(value.get('canonical_url') or value.get('url') or '').hostname
    if not expected or not actual:return
    expected=expected.lower().removeprefix('www.');actual=actual.lower().removeprefix('www.')
    greenhouse_hosts={'boards.greenhouse.io','job-boards.greenhouse.io','job-boards.eu.greenhouse.io','boards.eu.greenhouse.io'}
    if expected!=actual and not (provider=='greenhouse' and expected in greenhouse_hosts and actual in greenhouse_hosts):
        raise SourceError('saved_detail_url_host_mismatch')


def _jsonld_identity(value,target):
    from ..domain import canonicalize_url
    raw=value.get('raw') or {}
    identifier=raw.get('identifier')
    identifier=identifier.get('value') or identifier.get('name') if isinstance(identifier,dict) else identifier
    known_ids={str(value) for value in (target.get('external_id'),target.get('requisition_id')) if value is not None and value!=''}
    native_match=identifier is not None and str(identifier) in known_ids
    expected_url=canonicalize_url(target.get('canonical_url') or target.get('apply_url'))
    canonical_match=bool(expected_url and canonicalize_url(value.get('canonical_url'))==expected_url)
    native_expected=bool(target.get('requisition_id') or not canonicalize_url(str(target.get('external_id') or '')))
    if identifier is not None and native_expected and not native_match:
        raise SourceError('saved_jsonld_native_identity_mismatch')
    if not native_match and not canonical_match:raise SourceError('saved_jsonld_identity_mismatch')
    org=raw.get('hiringOrganization') or {}
    name=org.get('name')
    if name and target.get('company_name'):
        normalize=lambda text:re.sub(r'[^a-z0-9]','',str(text).lower())
        names=[target['company_name']]+list(target.get('company_aliases') or [])
        if normalize(name) not in {normalize(item) for item in names}:
            raise SourceError('saved_jsonld_employer_mismatch')


async def targeted_refresh(c):
    c.scope = "targeted"
    records = c.source.config.get("refresh_jobs") or [{"external_id": x} for x in c.source.config.get("refresh_external_ids", [])]
    ids = {str(x["external_id"]) for x in records if x.get("external_id") is not None}
    if not ids:
        raise SourceError("refresh_requires_external_ids")
    provider = c.source.provider
    if provider == 'unstop':
        from .discovery import unstop
        await unstop(c)
        c.jobs={key:value for key,value in c.jobs.items() if key in ids}
        if ids-c.jobs.keys():c.problem('saved_unstop_ids_not_in_bounded_window; availability_uncertain')
        c.scope='targeted';return
    if provider == 'internshala':
        from ..domain import canonicalize_url
        for target in records[:c.max_details]:
            url = target.get('canonical_url')
            if not url:
                c.problem('saved_detail_url_missing'); continue
            try:
                c.detail_requests+=1
                response=await c.http.request('GET',url)
                if canonicalize_url(str(response.url))!=canonicalize_url(url):
                    raise SourceError('saved_internshala_redirect_identity_mismatch')
                normalize=lambda text:re.sub(r'[^a-z0-9]','',str(text).lower())
                matches=[item for item in parse_internshala(c.source,response.text,url)
                    if canonicalize_url(item.get('canonical_url'))==canonicalize_url(url)
                    and (not target.get('company_name') or normalize(item.get('company_name'))==normalize(target['company_name']))]
                if len(matches)!=1 or not matches[0].get('description'):
                    raise SourceError('saved_internshala_detail_identity_or_description_mismatch')
                value={**matches[0],'external_id':str(target['external_id'])}
                c.add(value)
            except SourceError as exc:c.problem(str(exc))
        if len(records)>c.max_details:c.problem('saved_refresh_limit_reached')
        if not c.jobs: c.problem('internshala_detail_unrecognized; availability_uncertain')
        c.finish(len(c.jobs)==len(ids)); return
    # These APIs deliver all full descriptions in one inexpensive response.
    if provider in {"ashby", "recruitee"}:
        await {"ashby": ashby, "recruitee": recruitee}[provider](c)
        c.jobs = {key: value for key, value in c.jobs.items() if key in ids}
        targets={str(row.get('external_id')):row for row in records}
        for key,value in list(c.jobs.items()):
            try:_same_host(targets[key],value,provider)
            except SourceError as exc:c.problem(str(exc));c.jobs.pop(key)
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
                if url and urlsplit(url).hostname!=urlsplit(origin).hostname:
                    raise SourceError('saved_workday_url_host_mismatch')
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
                native_id,native_req=workday_listing_identifiers({'externalPath':path,'bulletFields':[d.get('jobReqId')]})
                if external_id not in {native_id,path} or not native_req or (target.get('requisition_id') and native_req!=str(target['requisition_id'])):
                    raise SourceError('saved_workday_native_identity_mismatch')
                value = job(c.source, external_id, d["title"], description=d["jobDescription"],
                    url=f"{origin}/{site}{path}", location=[d.get("location")] + (d.get("additionalLocations") or []),
                    requisition_id=d.get("jobReqId") or target.get("requisition_id"),
                    posted_at=date_value(d.get("startDate")), deadline=date_value(d.get("endDate")),
                    employment_type=d.get("timeType"), work_mode=d.get("remoteType") or "unknown", raw=payload)
            elif provider == "greenhouse":
                token = slug(c.source)
                d = await c.http.json("GET", f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{quote(external_id, safe='')}")
                _native_id(target,d.get('id'))
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
                _native_id(target,x.get('Id'))
                description = "\n".join(x.get(k) or "" for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"))
                value = job(c.source, external_id, x.get("Title") or target.get("title"), description=description, url=url,
                    location=x.get("PrimaryLocation"), country=x.get("PrimaryLocationCountry"), raw=d,
                    deadline=date_value(x.get("PostingEndDate")), requisition_id=target.get("requisition_id"))
            elif provider == "eightfold":
                d = await c.http.json("GET", c.source.origin + "/api/pcsx/position_details", params={"position_id": external_id,
                    "domain": c.source.config.get("domain") or c.source.company_domain, "hl": "en"})
                x = d.get("data") or {}
                _native_id(target,x.get('id') or x.get('positionId') or x.get('position_id'))
                value = job(c.source, external_id, x.get("name") or x.get("title") or x.get("jobTitle") or target.get("title"),
                    description=x.get("jobDescription"), url=url or f"{c.source.origin}/careers/job/{external_id}",
                    location=x.get("locations"), raw=d, requisition_id=x.get("atsJobId") or target.get("requisition_id"))
            elif provider == "smartrecruiters":
                token = slug(c.source)
                x = await c.http.json("GET", f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{quote(external_id, safe='')}")
                _native_id(target,x.get('id'))
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
                from ..domain import canonicalize_url
                response=await c.http.request('GET',url)
                if canonicalize_url(str(response.url))!=canonicalize_url(url):
                    raise SourceError('saved_detail_redirect_identity_mismatch')
                matches = parse_jsonld(c.source, response.text, str(response.url))
                if len(matches) != 1:
                    raise SourceError("saved_detail_not_unambiguous_jsonld; availability_uncertain")
                value = matches[0]
                _jsonld_identity(value,target)
                value["external_id"] = external_id
                value["requisition_id"] = target.get("requisition_id") or value.get("requisition_id")
            if not value.get("title") or not value.get("description"):
                raise SourceError("saved_detail_incomplete")
            _same_host(target,value,provider)
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
