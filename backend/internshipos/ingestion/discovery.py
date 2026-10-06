"""Supplemental discovery. Query results never prove absence or legitimacy."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from html import escape
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from .adapters import rows_at
from .parsing import compensation, date_value, job, location_text
from .types import SchemaError, SourceError


def parse_unstop(source, x):
    d = x.get("jobDetail") or {}
    registration = x.get("regnRequirements") or {}
    org = x.get("organisation") or {}
    currency = "INR" if d.get("currency") in {"fa-rupee", "INR", "₹"} else d.get("currency")
    pay = compensation(d.get("min_salary"), d.get("max_salary"), currency, d.get("pay_in"),
                       label="Unpaid" if d.get("paid_unpaid") == "unpaid" else None)
    # Top-level isPaid refers to a different platform payment concept.
    result = job(source, x.get("id"), x.get("title"), description=x.get("details"),
        url=x.get("seo_url") or urljoin("https://unstop.com/", x.get("public_url") or ""),
        location=x.get("locations") or x.get("address_with_country_logo"), raw=x,
        company_name=org.get("name") or source.company_name, company_domain=None,
        work_mode={"wfh": "remote", "in_office": "onsite", "hybrid": "hybrid"}.get(d.get("type"), "unknown"),
        employment_type=x.get("subtype"), compensation=pay,
        deadline=date_value(registration.get("end_regn_dt") or x.get("end_date")),
        # Do not promote AI-tagged skills into confirmed requirements.
        skills=list(dict.fromkeys(s.get("skill") for s in x.get("required_skills", [])
                                  if s.get("skill") and not (s.get("pivot") or {}).get("ai_generated"))),
        evidence=[{"kind": "platform_record", "source_url": source.url, "updated_at": x.get("updated_at"),
                   "eligibility_raw": registration.get("eligibility"), "skills_raw": x.get("required_skills"),
                   "company_verification": "unverified_discovery"}],
    )
    return result


async def unstop(c):
    c.scope = "discovery"
    for page in range(1, min(c.max_pages, int(c.source.config.get("pages", 3))) + 1):
        params = {"opportunity": "internships", "page": page, "per_page": 20}
        params.update(c.source.config.get("params", {}))
        payload = await c.http.json("GET", "https://unstop.com/api/public/opportunity/search-result", params=params)
        data = payload.get("data") or {}
        items = rows_at(data, "data")
        c.reported_total = data.get("total")
        new = sum(c.add(parse_unstop(c.source, x)) for x in items)
        if not data.get("next_page_url"):
            c.finish(True); return
        if not new:
            raise SourceError("discovery_pagination_repeated_page")
    c.warnings.append("bounded_discovery_window; not_a_full_inventory")
    c.finish(True)


async def freehire(c):
    c.scope = "discovery"
    params = {"countries": "in", "employment_type": "internship", "limit": 30}
    params.update(c.source.config.get("params", {}))
    # Agent search returns full descriptions rather than the search-index snippet.
    payload = await c.http.json("GET", "https://freehire.me/api/v1/agent/jobs/search", params=params)
    items = rows_at(payload, "data")
    c.reported_total = (payload.get("meta") or {}).get("total")
    for x in items:
        if x.get("closed_at"):
            continue
        c.add(job(c.source, x.get("public_slug") or f"{x.get('source')}:{x.get('external_id')}", x.get("title"),
            description=x.get("description"), url=x.get("url"), location=x.get("location"), raw=x,
            company_name=x.get("company"), company_domain=None, posted_at=date_value(x.get("posted_at")),
            # Upstream enrichment mislabels internships: keep as raw, not authoritative employment_type.
            evidence=[{"kind": "aggregator", "source_url": f"https://freehire.me/job/{x.get('public_slug')}",
                       "original_provider": x.get("source"), "original_external_id": x.get("external_id"),
                       "upstream_enrichment_is_inferred": True}]))
    if c.reported_total is not None and c.reported_total > len(items):
        c.warnings.append("bounded_discovery_window; not_a_full_inventory")
    c.finish(True)


async def github_tracker(c):
    """Tracker URLs are supplemental leads; no freshness or eligibility claims."""
    c.scope='discovery'
    markdown=await c.http.text(c.source.url)
    last_company=''
    header=False
    for line in markdown.splitlines():
        if not line.lstrip().startswith('|'):continue
        cells=line.strip().split('|')[1:-1]
        if len(cells)<4:continue
        if 'company' in cells[0].lower() and re.search('position|role|job',cells[1],re.I):header=True;continue
        if not header or re.fullmatch(r'[\s:|-]+',line):continue
        company=BeautifulSoup(cells[0],'html.parser').get_text(' ',strip=True)
        if '↳' in company or not company:company=last_company
        else:last_company=company
        title=BeautifulSoup(cells[1],'html.parser').get_text(' ',strip=True)
        location=BeautifulSoup(cells[2],'html.parser').get_text(' ',strip=True)
        links=BeautifulSoup(cells[3],'html.parser').find_all('a',href=True)
        if not links:
            match=re.search(r'\]\((https?://[^)]+)\)',cells[3])
            target=match[1] if match else None
        else:target=links[0]['href']
        if not company or not title or not target:continue
        c.add(job(c.source,target,title,url=target,location=location,company_name=company,company_domain=None,
            raw={'row':line},evidence=[{'kind':'tracker_lead','source_url':c.source.url,'original_url':target,'age_raw':cells[4].strip() if len(cells)>4 else None}]))
    if not header:raise SchemaError('tracker_table_schema_missing')
    c.finish(True)


async def jobspy(c):
    """Isolated process allows a hard stop; package errors cannot become zeros."""
    c.scope = "discovery"
    site = c.source.config.get("site") or c.source.provider
    if site == "jobspy":
        site = "linkedin"
    if site not in {"linkedin", "indeed", "naukri", "google", "glassdoor", "zip_recruiter"}:
        raise SourceError("unsupported_jobspy_site")
    args = {"site": site, "search_term": c.source.config.get("search_term", "software intern"),
            "location": c.source.config.get("location", "India"),
            "results_wanted": min(int(c.source.config.get("results_wanted", 30)), 100)}
    interpreter = os.environ.get("JOBSPY_PYTHON") or sys.executable
    worker = str(Path(__file__).with_name("jobspy_worker.py").resolve())
    process = await asyncio.create_subprocess_exec(interpreter, '-I', worker,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(args).encode()), 75)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        process.kill()
        await process.wait()
        raise SourceError("jobspy_timeout")
    if process.returncode:
        raise SourceError("jobspy_unavailable_or_failed: " + stderr.decode(errors="replace")[-700:])
    try:
        payload = json.loads(stdout)
    except ValueError as exc:
        raise SchemaError("jobspy_invalid_worker_output") from exc
    log = payload.get("log", "")
    if re.search(r"captcha|recaptcha|initial cursor|error|429|403|406", log, re.I):
        c.problem("jobspy_reported_failure: " + log[-500:])
    for x in payload.get("records", []):
        direct = x.get("job_url_direct") or x.get("job_url")
        domain_url = x.get("company_url_direct") or ""
        c.add(job(c.source, x.get("id") or x.get("job_url"), x.get("title"),
            description=x.get("description"), url=direct, location=x.get("location"), raw=x,
            company_name=x.get("company"), company_domain=urlsplit(domain_url).hostname,
            employment_type=x.get("job_type"), posted_at=date_value(x.get("date_posted")),
            work_mode="remote" if x.get("is_remote") is True else "unknown",
            compensation=compensation(x.get("min_amount"), x.get("max_amount"), x.get("currency"), x.get("interval"),
                                      kind="employer_stated" if x.get("salary_source") == "direct_data" else "source_reported")))
    c.finish(True)


def detect_source(url: str) -> dict | None:
    p = urlsplit(url)
    host, parts = (p.hostname or "").lower(), [x for x in p.path.split("/") if x]
    if not host or p.scheme not in {"http", "https"} or p.username or p.password:
        return None
    provider, normalized = None, url
    rules = {"greenhouse.io": "greenhouse", "lever.co": "lever", "ashbyhq.com": "ashby", "smartrecruiters.com": "smartrecruiters",
             "myworkdayjobs.com": "workday", "myworkdaysite.com": "workday", "oraclecloud.com": "oracle", "eightfold.ai": "eightfold",
             "workable.com": "workable", "recruitee.com": "recruitee", "personio.com": "personio", "personio.de": "personio",
             "breezy.hr": "breezy", "pinpointhq.com": "pinpoint", "bamboohr.com": "bamboohr", "amazon.jobs": "amazon"}
    for suffix, candidate in rules.items():
        if host == suffix or host.endswith("." + suffix):
            provider = candidate; break
    if host == "apply.careers.microsoft.com":
        provider = "eightfold"
    if not provider:
        return None
    expected_hosts = {"greenhouse": {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io", "boards-api.greenhouse.io"},
                      "lever": {"jobs.lever.co", "jobs.eu.lever.co", "api.lever.co", "api.eu.lever.co"},
                      "ashby": {"jobs.ashbyhq.com", "api.ashbyhq.com"},
                      "workable": {"apply.workable.com"},
                      "smartrecruiters": {"careers.smartrecruiters.com", "jobs.smartrecruiters.com", "api.smartrecruiters.com"}}
    if provider in expected_hosts and (host not in expected_hosts[provider] or not parts):
        return None
    config = {}
    if provider in {"greenhouse", "lever", "ashby", "smartrecruiters", "workable"}:
        token = parts[0]
        if provider == "greenhouse":
            if host == "boards-api.greenhouse.io":
                if len(parts) < 3 or parts[:2] != ["v1", "boards"]:
                    return None
                token = parts[2]
            elif token == "embed":
                token = (parse_qs(p.query).get("for") or [None])[0]
            board_host = "job-boards.eu.greenhouse.io" if ".eu." in host else "job-boards.greenhouse.io"
        elif provider == "lever":
            if host.startswith("api."):
                if len(parts) < 3 or parts[:2] != ["v0", "postings"]:
                    return None
                token = parts[2]
            board_host = "jobs.eu.lever.co" if ".eu." in host else "jobs.lever.co"
        elif provider == "ashby":
            if host == "api.ashbyhq.com":
                if len(parts) < 3 or parts[:2] != ["posting-api", "job-board"]:
                    return None
                token = parts[2]
            board_host = "jobs.ashbyhq.com"
        elif provider == "smartrecruiters":
            if host == "api.smartrecruiters.com":
                if len(parts) < 3 or parts[:2] != ["v1", "companies"]:
                    return None
                token = parts[2]
            board_host = "careers.smartrecruiters.com"
        else:
            board_host = "apply.workable.com"
            if token == "j":  # A single application URL contains no employer board.
                return None
        if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+", unquote(token)):
            return None
        config["token"] = unquote(token)
        normalized = f"https://{board_host}/{quote(config['token'], safe='_.-')}"
    return {"provider": provider, "url": normalized, "config": config, "verified": False,
            "association_status": "candidate", "enabled": True, "poll_interval_hours": 24}


async def discover_company(name: str, domain=None, careers_url=None, *, trusted_domain=False,
                           client=None, resolve_dns=True) -> dict:
    """Record official-site-to-ATS evidence without equating reachability to trust.

    `trusted_domain` is supplied only for a previously verified employer domain.
    For new companies, the same links remain evidence awaiting identity review.
    """
    import httpx
    from datetime import datetime, timezone
    from .http import PublicHTTP, USER_AGENT
    checked = datetime.now(timezone.utc).isoformat()
    supplied_domain = urlsplit(domain if domain and "://" in domain else "https://" + str(domain or "")).hostname
    supplied_domain = supplied_domain.removeprefix("www.") if supplied_domain else None
    result = {"name": name, "domain": supplied_domain, "careers_url": careers_url,
              "verified": bool(trusted_domain and supplied_domain),
              "verification_status": "trusted_existing_domain" if trusted_domain and supplied_domain else "needs_review",
              "discovery_status": "pending", "checked_at": checked, "retry_after_hours": 168,
              "sources": [], "evidence": [], "warnings": []}
    if not domain and not careers_url:
        result.update(error="official_domain_or_careers_url_required", discovery_status="missing_domain", retry_after_hours=336)
        return result
    def is_official(url):
        host = (urlsplit(url).hostname or "").removeprefix("www.")
        return bool(supplied_domain and (host == supplied_domain or host.endswith("." + supplied_domain)))
    def career_links(html, base):
        return list(dict.fromkeys(urljoin(base, a["href"]) for a in BeautifulSoup(html, "html.parser").find_all("a", href=True)
            if re.search(r"careers?|jobs|open.positions|openings|vacancies|join.us|work.with.us", a.get_text(" ") + " " + a["href"], re.I)))
    target = (domain if str(domain).startswith(("https://", "http://")) else "https://" + str(domain)) if domain else careers_url
    # A known official careers page is a better first request than a marketing
    # homepage, which can have an unrelated bot policy or many footer links.
    if careers_url and is_official(careers_url):
        target = careers_url
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT}, trust_env=False)
    try:
        http = PublicHTTP(client, max_requests=8, resolve_dns=resolve_dns)
        response = await http.request("GET", target)
        final_url = str(response.url)
        official = is_official(final_url)
        official_redirect = is_official(target) and final_url != target and detect_source(final_url)
        result["evidence"].append({"kind": "public_site_reachable", "url": final_url,
                                   "status": response.status_code, "matches_supplied_domain": official})
        if supplied_domain and not official and not official_redirect:
            result["warnings"].append("website_redirected_to_other_domain; binding_requires_review")
        if official_redirect:
            # The binding is the official URL's observed redirect, not arbitrary
            # links found on a third-party board after following it.
            pages = [(target, f'<a href="{escape(final_url, quote=True)}">Careers redirect</a>', True)]
            links = []
            result["evidence"].append({"kind": "official_careers_redirect", "linked_from": target,
                                       "target": final_url, "observed_at": checked})
        else:
            pages = [(final_url, response.text, official)]
            links = career_links(response.text, final_url)
        if careers_url and is_official(careers_url) and careers_url not in links:
            links.append(careers_url)
        # Inspect a few official career pages, never arbitrary unrelated links.
        pending = list(links)
        inspected = {final_url, target}
        fetched_pages = 0
        while pending and fetched_pages < 4:
            url = pending.pop(0)
            if url in inspected:
                continue
            inspected.add(url)
            if detect_source(url) or not is_official(url) or url == final_url:
                continue
            fetched_pages += 1
            try:
                page = await http.request("GET", url)
                if is_official(str(page.url)):
                    pages.append((str(page.url), page.text, True))
                    # Employers often separate their culture page from the
                    # actual openings page. Follow that bounded official chain.
                    pending.extend(u for u in career_links(page.text, str(page.url)) if u not in inspected)
                elif detect_source(str(page.url)):
                    # An official careers URL redirecting to an ATS is binding evidence.
                    pages.append((url, f'<a href="{escape(str(page.url), quote=True)}">Careers redirect</a>', True))
            except SourceError as exc:
                result["warnings"].append("career_page_unavailable: " + str(exc))
        found = {}
        for page_url, html, from_official in pages:
            parsed = BeautifulSoup(html, "html.parser")
            page_links = [urljoin(page_url, a["href"]) for a in parsed.find_all("a", href=True)]
            page_links += [urljoin(page_url, frame["src"]) for frame in parsed.find_all("iframe", src=True)]
            # Greenhouse documents an embeddable job-board script. Its `for`
            # token is an explicit board integration, even without an iframe.
            page_links += [urljoin(page_url, script["src"]) for script in parsed.find_all("script", src=True)
                           if "/embed/job_board/js" in urlsplit(urljoin(page_url, script["src"])).path
                           and (urlsplit(urljoin(page_url, script["src"])).hostname or "") in
                           {"boards.greenhouse.io", "boards.eu.greenhouse.io"}]
            if not supplied_domain:
                page_links.append(page_url)
            for link in page_links:
                source = detect_source(link)
                if not source:
                    continue
                binding = {"kind": "official_site_ats_link" if from_official else "unverified_page_ats_link",
                           "linked_from": page_url, "target": link, "observed_at": checked,
                           "official_domain_previously_verified": bool(trusted_domain), "company_name": name}
                source["verified"] = bool(from_official and trusted_domain)
                source["association_status"] = "verified" if source["verified"] else "candidate"
                source["config"].update(association_evidence=binding, association_status=source["association_status"])
                source["board"] = None
                if source["provider"] == "eightfold" and supplied_domain:
                    source["config"]["domain"] = supplied_domain
                prior = found.get(source["url"])
                if not prior or source["verified"]:
                    found[source["url"]] = source
                result["evidence"].append(binding)
        result["sources"] = list(found.values())
        if not found:
            candidates = [u for u in links if is_official(u)]
            if candidates:
                result["sources"] = [{"provider": "generic", "url": candidates[0], "board": None,
                    "config": {"association_evidence": {"kind": "official_careers_link", "linked_from": final_url, "target": candidates[0]}},
                    "verified": bool(trusted_domain and official), "association_status": "verified" if trusted_domain and official else "candidate",
                    "enabled": True, "poll_interval_hours": 24}]
        if careers_url and detect_source(careers_url) and not result["sources"]:
            # A submitted ATS URL remains a candidate if the official page did not link it.
            candidate = detect_source(careers_url)
            candidate["config"]["association_evidence"] = {"kind": "supplied_url_only", "target": careers_url}
            result["sources"].append(candidate)
        result["discovery_status"] = "sources_found" if result["sources"] else "no_careers_mapping_found"
        result["retry_after_hours"] = 720 if result["sources"] else 168
    except SourceError as exc:
        result.update(error=str(exc), discovery_status="fetch_failed", retry_after_hours=24)
    finally:
        if own:
            await client.aclose()
    return result
