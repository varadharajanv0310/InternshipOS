"""Idempotent registry/settings bootstrap. Creates no jobs or applicant facts."""
import json
from pathlib import Path

from sqlalchemy import func, select

from . import models as m

DEFAULT_SETTINGS = {
    "roles": ["SWE", "Data", "AI_ML", "Adjacent"],
    "locations": ["Chennai", "Bengaluru", "Remote India", "India"],
    "priority_poll_hours": 6, "normal_poll_hours": 12, "longtail_poll_hours": 24,
    "gmail_poll_minutes": 45, "ai_monthly_budget_usd": 2.5, "ai_enabled": False,
    "notifications_enabled": True, "theme": "system", "minimum_fit": 0,
    "closure_grace_hours": 48, "automatic_submission": False,
    "auto_apply": {"enabled": False, "providers": []}, "timezone": "Asia/Kolkata",
    "saved_detail_refresh_hours": 24,
    "personal_target_filter": False,
}
EMPTY_PROFILE = {"skills": [], "preferred_roles": [], "preferred_locations": [], "education": {},
                 "projects": [], "availability": {}, "github_username": ""}


def seed_database(db):
    for key, value in DEFAULT_SETTINGS.items():
        if db.get(m.Setting, key) is None:
            db.add(m.Setting(key=key, value=value))
    if not db.scalar(select(m.ProfileVersion.id).limit(1)):
        db.add(m.ProfileVersion(data=EMPTY_PROFILE.copy()))
    db.flush()
    seed_path = Path(__file__).parent / "data" / "company_seeds.json"
    if not seed_path.exists():
        # The independent ingestion package may be installed after the core package.
        db.commit()
        return {"companies_added": 0, "sources_added": 0, "seed_file_present": False}
    seeds = json.loads(seed_path.read_text(encoding="utf-8-sig"))
    if isinstance(seeds, dict):
        seeds = seeds.get("companies", seeds.get("items", []))
    companies_added = sources_added = 0
    for item in seeds:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        domain = str(item.get("domain") or "").lower().removeprefix("https://").removeprefix("http://").strip("/") or None
        company = db.scalar(select(m.Company).where(func.lower(m.Company.name) == name.lower()).limit(1))
        if company is None:
            company = m.Company(name=name, domain=domain, verified=bool(item.get("verified", False)),
                                careers_url=item.get("careers_url"), logo_url=item.get("logo_url"),
                                locations=item.get("locations", []), aliases=item.get("aliases", []),
                                metadata_json={"website": item.get("website"), "verification_status": item.get("verification_status", "candidate"),
                                               "provenance": item.get("provenance", {}), "seed": True})
            db.add(company)
            db.flush()
            companies_added += 1
        for source in item.get("sources", []):
            provider = str(source.get("provider") or "custom").lower()
            url = str(source.get("url") or source.get("board_url") or "").strip()
            if not url:
                continue
            exists = db.scalar(select(m.CompanySource.id).where(m.CompanySource.company_id == company.id, m.CompanySource.provider == provider, m.CompanySource.url == url).limit(1))
            if exists:
                continue
            association = source.get("association_status", "candidate")
            config = {**source.get("config", {}), "association_status": association, "provenance": source.get("provenance", item.get("provenance", {}))}
            db.add(m.CompanySource(company_id=company.id, provider=provider, url=url,
                                   tenant=source.get("tenant"), board=source.get("board"), config=config,
                                   verified=association == "verified", enabled=bool(source.get("enabled", association == "verified")),
                                   cadence_hours=int(source.get("poll_interval_hours", source.get("cadence_hours", 12))),
                                   priority={"priority": 1, "normal": 2, "longtail": 3}.get(source.get("priority"), source.get("priority", 2)), status="pending" if source.get("enabled") else "unverified"))
            db.flush()
            sources_added += 1
    if companies_added or sources_added:
        db.add(m.Activity(kind="registry.seeded", title=f"Imported {companies_added} companies and {sources_added} source candidates", entity_type="registry", data={"companies": companies_added, "sources": sources_added, "path": str(seed_path)}))
    db.commit()
    return {"companies_added": companies_added, "sources_added": sources_added, "seed_file_present": True}
