"""Licensed registry imports. Registry entries are candidates, not verification."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.parse import urlsplit

from . import SUPPORTED_PROVIDERS

JOBSEEK_SNAPSHOT = "4bf9a672b271841c034089b4464ea2210a2dc966"


def import_jobseek(companies_path, boards_path, *, selected_slugs=None):
    """Import local MIT CSVs without running Job Seek or making network requests."""
    with Path(companies_path).open(encoding="utf-8-sig", newline="") as handle:
        companies = list(csv.DictReader(handle))
    with Path(boards_path).open(encoding="utf-8-sig", newline="") as handle:
        boards = list(csv.DictReader(handle))
    result = []
    for company in companies:
        if selected_slugs is not None and company["slug"] not in selected_slugs:
            continue
        website = company.get("website") or ""
        domain = (urlsplit(website).hostname or "").removeprefix("www.")
        if not domain:
            continue
        sources = []
        for board in boards:
            if board["company_slug"] != company["slug"]:
                continue
            provider = board["monitor_type"]
            config = json.loads(board.get("monitor_config") or "{}")
            if provider not in SUPPORTED_PROVIDERS:
                config["registry_provider"] = provider
                provider = "generic"
            if provider == "workday":
                config["search_text"] = "intern"
                config.update(country_name="India", early_career=True)
            if provider == "eightfold":
                config.update(domain=domain, query="intern")
            if provider == "oracle_hcm":
                config["keyword"] = "intern"
            if provider == "amazon":
                config.update(base_query="intern", **{"normalized_country_code[]": "IND"})
            config.update(registry_source="colophon-group/jobseek", registry_snapshot=JOBSEEK_SNAPSHOT,
                          association_status="candidate")
            sources.append({"provider": provider, "url": board["board_url"], "board": board["board_slug"],
                            "config": config, "association_status": "candidate", "verified": False,
                            "enabled": True, "poll_interval_hours": 24})
        result.append({"name": company["name"], "domain": domain, "website": website,
                       "careers_url": sources[0]["url"] if sources else None,
                       "verified": False, "verification_status": "registry_candidate",
                       "provenance": {"source": "https://github.com/colophon-group/jobseek", "commit": JOBSEEK_SNAPSHOT,
                                      "license": "MIT", "company_slug": company["slug"]}, "sources": sources})
    return result


def import_openjobs(payload):
    """Return provider/tenant candidate rows from a CC0 Open Jobs registry object.

    Support its provider-keyed slug lists without inventing employer identity.
    The caller validates boards before attaching them to a company.
    """
    if not isinstance(payload, dict):
        raise ValueError("Expected a provider-keyed registry object")
    candidates = []
    providers = payload.get("ats", payload)
    for provider, values in providers.items():
        if provider not in {"greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee"}:
            continue
        if isinstance(values, dict):
            values = values.get("live", values.get("slugs", []))
        if not isinstance(values, list):
            continue
        for value in values:
            token = value if isinstance(value, str) else value.get("slug") if isinstance(value, dict) else None
            if not token or not all(c.isalnum() or c in "-_" for c in token):
                continue
            patterns = {"greenhouse": "https://job-boards.greenhouse.io/{}", "lever": "https://jobs.lever.co/{}",
                        "ashby": "https://jobs.ashbyhq.com/{}", "workable": "https://apply.workable.com/{}",
                        "smartrecruiters": "https://careers.smartrecruiters.com/{}", "recruitee": "https://{}.recruitee.com"}
            candidates.append({"provider": provider, "url": patterns[provider].format(token),
                "config": {"token": token}, "association_status": "candidate", "verified": False,
                "provenance": {"source": "https://github.com/elliottdehn/open-jobs", "license": "CC0-1.0"}})
    return candidates


def default_discovery_sources():
    """Unattached discovery feeds; their employers are resolved per job record."""
    from ..search_policy import expanded_sources
    return [
        {"name": "Unstop internships", "provider": "unstop", "url": "https://unstop.com/internships",
         "config": {"pages": 3}, "cadence_hours": 12, "enabled": True},
        {"name": "Internshala computer science", "provider": "internshala", "url": "https://internshala.com/internships/computer-science-internship/",
         "config": {}, "cadence_hours": 12, "enabled": True},
        {"name": "Freehire India internships", "provider": "freehire", "url": "https://freehire.me/api/v1/agent/jobs/search",
         "config": {"params": {"countries": "in", "employment_type": "internship", "limit": 30}}, "cadence_hours": 12, "enabled": True},
        {"name": "LinkedIn India", "provider": "linkedin", "url": "https://www.linkedin.com/jobs/",
         "config": {"search_term": "software intern", "location": "India", "results_wanted": 30}, "cadence_hours": 24, "enabled": True},
        {"name": "Indeed India", "provider": "indeed", "url": "https://in.indeed.com/",
         "config": {"search_term": "data science intern", "location": "India", "results_wanted": 30}, "cadence_hours": 24, "enabled": True},
        {"name": "Naukri India", "provider": "naukri", "url": "https://www.naukri.com/",
         "config": {"search_term": "software intern", "location": "India", "results_wanted": 20,
                    "disabled_reason": "CAPTCHA observed; manual capture available"}, "cadence_hours": 24, "enabled": False},
    ] + expanded_sources()
