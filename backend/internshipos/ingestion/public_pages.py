"""Data-only public page readers; embedded JSON is never executed as JavaScript."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from .parsing import date_value, job, parse_jsonld
from .types import SchemaError, SourceError


async def gem(c):
    """Documented unauthenticated Gem Job Board API; content is inline HTML.

    https://api.gem.com/job_board/v0/reference -- GET job_posts has no paging.
    Application submission endpoints are intentionally never used.
    """
    from .adapters import inventory_finished
    board = urlsplit(c.source.url)
    if board.query or not re.fullmatch(r'/[A-Za-z0-9_-]+/?', board.path):
        raise SchemaError('gem_unfiltered_board_required')
    slug = board.path.strip('/')
    rows = await c.http.json('GET', f'https://api.gem.com/job_board/v0/{slug}/job_posts/')
    if not isinstance(rows, list):
        raise SchemaError('gem_job_posts_array_missing')
    c.scope = 'full'
    c.reported_total = len(rows)
    for x in rows:
        if not isinstance(x, dict) or not x.get('id') or not x.get('title'):
            raise SchemaError('gem_listing_identity_missing')
        native = urlsplit(str(x.get('absolute_url') or ''))
        if native.scheme != 'https' or native.hostname != 'jobs.gem.com' or native.path.rstrip('/') != f'/{slug}/{x["id"]}' or native.username:
            raise SchemaError('gem_listing_board_identity_mismatch')
        item = job(c.source, x['id'], x['title'], url=x['absolute_url'],
                   description=x.get('content') or x.get('content_plain') or '',
                   location=x.get('location'), requisition_id=x.get('requisition_id'),
                   employment_type=x.get('employment_type'),
                   work_mode={'remote': 'remote', 'hybrid': 'hybrid', 'in_office': 'onsite'}.get(x.get('location_type'), 'unknown'),
                   posted_at=date_value(x.get('first_published_at')), raw=x)
        if not c.add(item):
            c.problem('gem_duplicate_listing')
        if not item['description']:
            c.problem('full_description_unavailable')
    inventory_finished(c, len(c.jobs) == len(rows))
    c.next_detail_cursor = 0
    c.finish(not c.errors)


async def trakstar(c):
    """Native SSR Trakstar cards and bounded JDs; page discovery cannot close jobs."""
    from .adapters import inventory_finished, rotating_details
    c.scope = 'discovery'
    soup = BeautifulSoup(await c.http.text(c.source.url), 'html.parser')
    container = soup.select_one('.js-openings-list')
    if container is None:
        raise SchemaError('trakstar_native_openings_missing')
    records = []
    for card in container.select('.js-careers-page-job-list-item'):
        path = card.get('data-href') or ''
        title = card.select_one('.js-job-list-opening-name')
        loc = card.select_one('.js-job-list-opening-loc')
        if not re.fullmatch(r'/jobs/fk[0-9a-z]+/?', path) or title is None:
            raise SchemaError('trakstar_listing_identity_missing')
        records.append({'external_id': path.strip('/').split('/')[-1],
                        'title': title.get('title') or title.get_text(' ', strip=True),
                        'location': loc.get('title') or loc.get_text(' ', strip=True) if loc else '',
                        'url': urljoin(c.source.origin, path)})
    def parse(x, description=''):
        return job(c.source, x['external_id'], x['title'], url=x['url'],
                   location=x['location'], description=description, raw=x)
    for x in records:
        if not c.add(parse(x)):
            c.problem('trakstar_duplicate_listing')
    c.reported_total = len(records)
    # Covers the evidenced SSR list only, not an assertion about undisclosed pages.
    inventory_finished(c, not c.errors)
    c.warnings.append('native_page_discovery_only; no_whole_board_closure')
    async def enrich(x):
        html = await c.detail_text(x['url'])
        detail = BeautifulSoup(html or '', 'html.parser')
        title = detail.select_one('.js-job-title')
        if title is None or title.get_text(' ', strip=True).casefold() != x['title'].casefold():
            c.problem('trakstar_detail_identity_mismatch')
            return parse(x)
        node = detail.select_one('.jobdesciption')  # Native site's spelling.
        return parse(x, str(node) if node else '')
    await rotating_details(c, records, enrich)
    c.finish(not c.errors)


def assigned_json(html, variable, *, json_parse=False):
    """Read only a named literal JSON assignment, not general script expressions."""
    if not re.fullmatch(r"(?:window\.)?[A-Za-z_$][A-Za-z0-9_$]*", variable):
        raise SchemaError("embedded_json_invalid_variable")
    for script in BeautifulSoup(html, "html.parser").find_all("script"):
        text = script.string or ""
        match = re.search(r"(?<![\w.])" + re.escape(variable) + r"\s*=\s*" +
                          (r"JSON\.parse\(\s*" if json_parse else ""), text)
        if not match:
            continue
        try:
            value, end = json.JSONDecoder().raw_decode(text[match.end():])
            trailing = text[match.end() + end:].lstrip()
            if json_parse:
                if not isinstance(value, str) or not trailing.startswith(")"):
                    raise ValueError("literal JSON.parse required")
                value = json.loads(value)
            elif trailing and trailing[0] not in ";\n":
                raise ValueError("literal assignment required")
            return value
        except (ValueError, TypeError) as exc:
            raise SchemaError("embedded_json_not_literal_data") from exc
    raise SchemaError("embedded_json_assignment_missing")


def apple_state(html):
    return assigned_json(html, "window.__staticRouterHydrationData", json_parse=True)


async def apple(c):
    """Apple's public React Router loader, including bounded native full details."""
    from .adapters import cursor_at, inventory_finished, reported_count, rotating_details
    c.scope = "query"  # Public regional/query pages never retire a whole board.
    start = cursor_at(c.source, "listing_cursor")
    c.next_listing_cursor = start
    records = []
    complete = False
    def parse(x, detail=None):
        # Apple listings explicitly contain jobSummary, not the full job detail.
        d = detail or {}
        desc = "\n\n".join(d[k] for k in
                           ("jobSummary", "description", "summary", "responsibilities", "minimumQualifications",
                            "preferredQualifications", "educationAndExperience", "additionalRequirements") if d.get(k))
        url = c.source.origin + "/en-us/details/" + str(x.get("positionId")) + "/" + str(x.get("transformedPostingTitle"))
        return job(c.source, x.get("id") or x.get("positionId"), x.get("postingTitle"),
                   url=url, location=x.get("locations"), description=desc,
                   requisition_id=x.get("reqId"), posted_at=date_value(x.get("postDateInGMT")),
                   raw={"listing": x, "detail": d})
    for page in range(start, start + c.max_pages):
        params = {key: values[-1] for key, values in parse_qs(urlsplit(c.source.url).query).items()}
        params.update(c.source.config.get("params") or {})
        params["page"] = page + 1
        html = await c.http.text(c.source.url, params=params)
        state = apple_state(html)
        data = (state.get("loaderData") or {}).get("search") or {}
        rows = data.get("searchResults")
        if not isinstance(rows, list):
            raise SchemaError("apple_search_results_missing")
        total = reported_count(data.get("totalRecords"), required=True)
        if c.reported_total is not None and total != c.reported_total:
            c.problem("inventory_changed_during_scan")
        c.reported_total = total
        new = 0
        for x in rows:
            if not isinstance(x, dict) or not x.get("positionId") or not x.get("transformedPostingTitle"):
                raise SchemaError("apple_listing_identity_missing")
            accepted = c.add(parse(x)); new += accepted
            if accepted:
                records.append(x)
        c.next_listing_cursor = page + 1
        if rows and new != len(rows):
            c.problem("pagination_repeated_page"); break
        if (page + 1) * 20 >= total:
            complete = start == 0 and len(c.jobs) == total and not c.errors
            c.next_listing_cursor = 0
            break
        if not rows:
            c.problem("apple_pagination_incomplete"); c.next_listing_cursor = 0; break
    else:
        c.problem("page_limit_reached")
    inventory_finished(c, complete)
    async def enrich(x):
        url = parse(x)["canonical_url"]
        html = await c.detail_text(url)
        if not html:
            return parse(x)
        ld = parse_jsonld(c.source, html, url)
        if ld:
            matching = [j for j in ld if j["canonical_url"].split("?")[0].rstrip("/") == url.rstrip("/")]
            if len(matching) == 1:
                return {**parse(x), **{k: v for k, v in matching[0].items()
                        if k in {"description", "description_html", "location", "employment_type", "deadline"}},
                        "raw": {"listing": x, "detail_jsonld": matching[0]["raw"]}}
        state = apple_state(html)
        loaders = state.get("loaderData") or {}
        detail = loaders.get("jobDetails") or loaders.get("details") or loaders.get("jobDetail") or {}
        if not isinstance(detail, dict):
            raise SchemaError("apple_detail_object_missing")
        detail = detail.get("jobsData") or detail.get("jobDetail") or detail.get("jobDetails") or detail
        if not isinstance(detail, dict):
            raise SchemaError("apple_detail_object_missing")
        identities = [detail[key] for key in ("positionId", "jobNumber") if detail.get(key) is not None]
        if not identities or any(str(actual) != str(x["positionId"]) for actual in identities) or (
            detail.get("id") is not None and str(detail["id"]) != str(x.get("id"))
        ):
            c.problem("apple_detail_identity_mismatch"); return parse(x)
        return parse(x, detail)
    await rotating_details(c, records, enrich)
    c.finish(complete or (start > 0 and c.next_listing_cursor == 0 and not c.errors))


async def recruiterflow(c):
    """Public SSR listings grouped by department; full target JDs use native pages."""
    from .adapters import inventory_finished, rotating_details
    c.scope = "discovery"
    data = assigned_json(await c.http.text(c.source.url), "window.jobsList")
    groups = data.get("group") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        raise SchemaError("recruiterflow_group_missing")
    records = []
    def parse(x, description=""):
        url = urljoin(c.source.origin + "/", str(x.get("apply_link") or ""))
        return job(c.source, x.get("job_id"), x.get("job_name"), url=url,
                   location=x.get("details"), description=description,
                   employment_type=x.get("employment_type"), work_mode=x.get("remote_type") or "unknown",
                   posted_at=date_value(x.get("last_opened")), raw=x)
    for group in groups:
        if not isinstance(group, list) or len(group) != 2 or not isinstance(group[1], list):
            raise SchemaError("recruiterflow_group_schema_changed")
        for x in group[1]:
            if not isinstance(x, dict) or not x.get("job_id") or not x.get("apply_link"):
                raise SchemaError("recruiterflow_listing_identity_missing")
            if c.add(parse(x)):
                records.append(x)
            else:
                c.problem("recruiterflow_duplicate_listing")
    c.reported_total = len(records)
    inventory_finished(c, not c.errors)
    async def enrich(x):
        url = parse(x)["canonical_url"]
        html = await c.detail_text(url)
        if not html:
            return parse(x)
        for item in parse_jsonld(c.source, html, url):
            if item["canonical_url"].rstrip("/") == url.rstrip("/"):
                return {**parse(x), "description": item["description"], "description_html": item["description_html"]}
        soup = BeautifulSoup(html, "html.parser")
        node = soup.select_one(".job-description")
        return parse(x, str(node) if node else "")
    await rotating_details(c, records, enrich)
    c.finish(not c.errors)


def kula_records(html):
    """Read the public SSR job array and UTF-8 Flight text references as data."""
    fragments = []
    for script in BeautifulSoup(html, "html.parser").find_all("script"):
        text = script.string or ""
        for match in re.finditer(r"self\.__next_f\.push\(", text):
            try:
                fragment, _ = json.JSONDecoder().raw_decode(text[match.end():])
            except ValueError:
                continue
            if isinstance(fragment, list) and len(fragment) == 2 and fragment[0] == 1 and isinstance(fragment[1], str):
                fragments.append(fragment[1])
    flight = "".join(fragments)
    match = re.search(r'"jobs"\s*:\s*', flight)
    if not match:
        raise SchemaError("kula_public_job_array_missing")
    try:
        rows, _ = json.JSONDecoder().raw_decode(flight[match.end():])
    except ValueError as exc:
        raise SchemaError("kula_public_job_array_invalid") from exc
    if not isinstance(rows, list):
        raise SchemaError("kula_public_job_array_invalid")
    encoded = flight.encode("utf-8")
    texts = {}
    # Flight text records terminate by their explicit byte length, not a newline;
    # one record can be immediately followed by the next <id>:T header.
    for record in re.finditer(rb"([0-9a-f]+):T([0-9a-f]+),", encoded):
        size = int(record.group(2), 16)
        body = encoded[record.end():record.end() + size]
        if len(body) != size:
            raise SchemaError("kula_truncated_text_reference")
        try:
            texts[record.group(1).decode()] = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SchemaError("kula_invalid_text_reference") from exc
    return rows, texts


async def kula(c):
    from .adapters import inventory_finished
    c.scope = "discovery"  # SSR list is not a full ATS absence proof.
    html = await c.http.text(c.source.url)
    rows, texts = kula_records(html)
    soup = BeautifulSoup(html, "html.parser")
    links = {}
    prefix = urlsplit(c.source.url).path.rstrip("/") + "/"
    for a in soup.find_all("a", href=True):
        url = urljoin(c.source.url, a["href"])
        if urlsplit(url).netloc != urlsplit(c.source.url).netloc:
            continue
        path = urlsplit(url).path
        if path.startswith(prefix):
            match = re.match(r"(\d+)-", path[len(prefix):])
            if match:
                links[match[1]] = url
    for x in rows:
        if not isinstance(x, dict) or x.get("id") is None or not isinstance(x.get("ats_job"), dict):
            raise SchemaError("kula_job_schema_changed")
        if x.get("listed") is not True or x.get("is_confidential") is True or x.get("kind") not in {"external", "internal_and_external"}:
            continue
        url = links.get(str(x["id"]))
        if not url:
            c.problem("kula_native_job_url_missing"); continue
        ats = x["ats_job"]
        description = ats.get("job_description") or ""
        if re.fullmatch(r"\$[0-9a-f]+", description):
            description = texts.get(description[1:], "")
        if not description:
            c.problem("kula_description_reference_missing")
        offices = ats.get("offices") or []
        c.add(job(c.source, x["id"], x.get("title"), url=url, description=description,
                  location=[o.get("location") for o in offices if isinstance(o, dict)],
                  employment_type=ats.get("work_type_name") or ats.get("employment_type"),
                  work_mode="remote" if ats.get("workplace") == "remote" else "onsite" if ats.get("workplace") == "office" else "unknown",
                  posted_at=date_value(x.get("launch_at")), deadline=date_value(x.get("end_at")), raw=x))
    c.reported_total = len(rows)
    inventory_finished(c, not c.errors)
    c.finish(not c.errors)


async def google_careers(c):
    """Google's rendered public cards and identity-bound active detail pane."""
    from .adapters import cursor_at, inventory_finished, rotating_details
    c.scope = "query"
    start = cursor_at(c.source, "listing_cursor")
    c.next_listing_cursor = start
    records = []
    terminated = False
    for page in range(start, start + c.max_pages):
        params = {k: v[-1] for k, v in parse_qs(urlsplit(c.source.url).query).items()}
        params.update(c.source.config.get("params") or {})
        params["page"] = page + 1
        response = await c.http.request("GET", c.source.url, params=params)
        soup = BeautifulSoup(response.text, "html.parser")
        base = soup.find("base", href=True)
        base_url = urljoin(str(response.url), base["href"]) if base else str(response.url)
        if urlsplit(base_url).netloc != urlsplit(c.source.url).netloc:
            raise SchemaError("google_document_base_identity_mismatch")
        cards = soup.select("li.lLd3Je")
        if not cards:
            raise SchemaError("google_public_job_cards_missing")
        new = 0
        for card in cards:
            title = card.select_one("h3.QJPWVe")
            links = [urljoin(base_url, a["href"]) for a in card.find_all("a", href=True)]
            targets = [u for u in links if urlsplit(u).netloc == urlsplit(c.source.url).netloc
                       and re.fullmatch(r"/about/careers/applications/jobs/results/\d+-[^/]+/?", urlsplit(u).path)]
            if not title or len(set(targets)) != 1:
                raise SchemaError("google_listing_identity_missing")
            url = targets[0]
            ident = re.search(r"/results/(\d+)-", urlsplit(url).path)[1]
            locations = list(dict.fromkeys(x.get_text(" ", strip=True) for x in card.select("span.r0wTof")))
            item = job(c.source, ident, title.get_text(" ", strip=True), url=url, location=locations,
                       raw={"native_id": ident, "listing_url": str(response.url)})
            if c.add(item):
                records.append({**item, "id": ident}); new += 1
        c.next_listing_cursor = page + 1
        if new != len(cards):
            c.problem("pagination_repeated_page"); break
        next_page = any((parse_qs(urlsplit(urljoin(base_url, a["href"])).query).get("page") or [None])[-1] == str(page + 2)
                        for a in soup.find_all("a", href=True))
        if not next_page:
            terminated = True; c.next_listing_cursor = 0; break
    else:
        c.problem("page_limit_reached")
    inventory_finished(c, start == 0 and terminated and not c.errors)
    async def enrich(x):
        c.detail_requests += 1
        try:
            response = await c.http.request("GET", x["canonical_url"])
        except SourceError as exc:
            c.problem("detail_fetch_failed: " + str(exc)); return x
        actual_id = re.search(r"/results/(\d+)-", urlsplit(str(response.url)).path)
        if not actual_id or actual_id[1] != x["external_id"] or urlsplit(str(response.url)).netloc != urlsplit(c.source.url).netloc:
            c.problem("google_detail_identity_mismatch"); return x
        soup = BeautifulSoup(response.text, "html.parser")
        pane = soup.select_one('div.DkhPwc[data-id="' + x["external_id"] + '"]')
        title = pane.select_one("h2.p1N2lc") if pane else None
        if not title or title.get_text(" ", strip=True) != x["title"]:
            c.problem("google_detail_identity_mismatch"); return x
        sections = []
        headings = []
        for heading in pane.find_all("h3"):
            text = heading.get_text(" ", strip=True)
            if text.rstrip(":") in {"Minimum qualifications", "Preferred qualifications", "About the job", "Responsibilities"}:
                headings.append(text.rstrip(":")); sections.append(str(heading.parent))
        if "About the job" not in headings or "Responsibilities" not in headings:
            c.problem("google_full_description_sections_missing"); return x
        return job(c.source, x["external_id"], x["title"], url=x["canonical_url"],
                   location=x["location"], description="\n".join(dict.fromkeys(sections)),
                   raw={"native_id": x["external_id"], "verified_detail_url": str(response.url)})
    await rotating_details(c, records, enrich)
    c.finish(terminated and not c.errors)
