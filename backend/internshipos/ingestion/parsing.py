"""Loss-conscious source field parsing. No title guesses become employer facts."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


def plain(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)
    soup = BeautifulSoup(value, "html.parser")
    for node in soup(["script", "style", "iframe", "object"]):
        node.decompose()
    return re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True)).strip()


def safe_link(value, base=""):
    if not value:
        return None
    url = urljoin(base, str(value))
    p = urlsplit(url)
    return url if p.scheme in {"http", "https"} and p.hostname and not p.username else None


def safe_html(value):
    soup = BeautifulSoup(str(value or ""), "html.parser")
    allowed = {"p", "br", "ul", "ol", "li", "strong", "b", "em", "i", "h1", "h2", "h3", "h4", "a", "blockquote", "pre", "code", "div", "span", "table", "tbody", "tr", "th", "td"}
    for node in list(soup.find_all(True)):
        if node.name is None:
            continue
        if node.name in {"script", "style", "iframe", "object", "embed", "form", "input", "button", "svg", "math"}:
            node.decompose()
        elif node.name not in allowed:
            node.unwrap()
        elif node.name == "a":
            link = safe_link(node.get("href"))
            node.attrs = {"href": link, "rel": "noopener noreferrer"} if link else {}
        else:
            node.attrs = {}
    return str(soup)


def location_text(value):
    if isinstance(value, list):
        return "; ".join(dict.fromkeys(filter(None, (location_text(x) for x in value))))
    if isinstance(value, dict):
        if "address" in value:
            return location_text(value["address"])
        keys = ("city", "addressLocality", "region", "state", "province", "addressRegion", "country", "addressCountry")
        bits = [location_text(value[k]) for k in keys if value.get(k)]
        return ", ".join(dict.fromkeys(bits)) or str(value.get("name") or value.get("location") or "")
    return str(value or "")


def date_value(value):
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / (1000 if value > 10_000_000_000 else 1), timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    # Preserve source's timezone/date precision. Relative date prose remains raw.
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return value
    return None


def compensation(minimum=None, maximum=None, currency=None, period=None, label=None, kind="employer_stated"):
    if all(v is None or v == "" for v in (minimum, maximum, label)):
        return {"kind": "unknown", "label": None, "min": None, "max": None, "currency": None, "period": None}
    return {"kind": kind, "label": label, "min": minimum, "max": maximum, "currency": currency, "period": period}


def job(source, external_id, title, *, description="", url=None, location="", raw=None, **fields):
    canonical = safe_link(url, source.url)
    html = str(description or "")
    result = {
        "external_id": str(external_id or canonical or ""), "title": plain(title),
        "description": plain(html), "description_html": safe_html(html),
        "location": location_text(location), "country": None, "work_mode": "unknown",
        "apply_url": canonical, "canonical_url": canonical, "requisition_id": None,
        "posted_at": None, "deadline": None, "employment_type": None,
        "compensation": compensation(), "skills": [], "company_name": source.company_name,
        "company_domain": source.company_domain or None, "raw": raw or {},
        "evidence": [{"kind": "source_record", "source_url": source.url, "provider": source.provider}],
    }
    result.update(fields)
    result["apply_url"] = safe_link(result.get("apply_url"), source.url)
    result["canonical_url"] = safe_link(result.get("canonical_url"), source.url)
    return result


def jsonld_objects(html):
    soup = BeautifulSoup(html, "html.parser")
    def walk(value):
        if isinstance(value, list):
            for item in value:
                yield from walk(item)
        elif isinstance(value, dict):
            yield value
            if "@graph" in value:
                yield from walk(value["@graph"])
    for node in soup.find_all("script", type=re.compile(r"application/ld\+json", re.I)):
        try:
            yield from walk(json.loads(node.string or node.get_text()))
        except (TypeError, ValueError):
            continue


def parse_jsonld(source, html, page_url=None):
    result = []
    for item in jsonld_objects(html):
        types = item.get("@type", [])
        if "JobPosting" not in (types if isinstance(types, list) else [types]):
            continue
        org = item.get("hiringOrganization") or {}
        identifier = item.get("identifier")
        if isinstance(identifier, dict):
            identifier = identifier.get("value") or identifier.get("name")
        url = safe_link(item.get("url") or page_url or source.url, source.url)
        pay = item.get("baseSalary") or {}
        if not isinstance(pay, dict):
            pay = {"value": pay}
        value = pay.get("value") or {}
        if not isinstance(value, dict):
            value = {"value": value}
        skills = item.get("skills") or []
        if isinstance(skills, str):
            skills = [x.strip() for x in re.split(r"[,;\n]", skills) if x.strip()]
        result.append(job(source, identifier or url, item.get("title"),
            description=item.get("description", ""), url=url, location=item.get("jobLocation"), raw=item,
            work_mode="remote" if str(item.get("jobLocationType", "")).upper() == "TELECOMMUTE" else "unknown",
            posted_at=date_value(item.get("datePosted")), deadline=date_value(item.get("validThrough")),
            employment_type=item.get("employmentType"), skills=skills,
            company_name=org.get("name") or source.company_name,
            company_domain=urlsplit(org.get("sameAs") or org.get("url") or "").hostname or source.company_domain or None,
            compensation=compensation(value.get("minValue", value.get("value")), value.get("maxValue"), pay.get("currency"), value.get("unitText")),
            evidence=[{"kind": "json_ld", "source_url": page_url or source.url,
                       "applicant_location_requirements": item.get("applicantLocationRequirements")}],
        ))
    return result


def stable_id(url):
    return hashlib.sha256(url.encode()).hexdigest()[:24]
