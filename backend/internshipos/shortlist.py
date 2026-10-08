"""Shared recommendation policy; unknowns never prove ineligibility or closure."""
from datetime import timedelta
import re

from sqlalchemy import select

from . import models as m
from .db import aware, utcnow
from .domain import canonicalize_url, parse_date

EXCLUSIONS_KEY = "shortlist_exclusions"


def exclusions(db):
    row = db.get(m.Setting, EXCLUSIONS_KEY)
    value = row.value if row and isinstance(row.value, dict) else {}
    return {key: list(dict.fromkeys(str(x) for x in value.get(key, []) if x))
            for key in ("opportunity_ids", "company_ids")}


def hidden(op, rules):
    return bool((op.data or {}).get("duplicate_of") or op.id in rules["opportunity_ids"] or op.company_id in rules["company_ids"]
                or set((op.data or {}).get("mirror_ids") or []) & set(rules["opportunity_ids"]))


def visibility_sql(op, rules):
    from sqlalchemy.orm import aliased
    mirrors = aliased(m.Opportunity)
    excluded_canonical_ids = select(mirrors.data["duplicate_of"].as_string()).where(mirrors.id.in_(rules["opportunity_ids"]), mirrors.data["duplicate_of"].as_string().is_not(None))
    return (op.data["duplicate_of"].as_string().is_(None)
            & op.id.not_in(rules["opportunity_ids"])
            & op.id.not_in(excluded_canonical_ids)
            & op.company_id.not_in(rules["company_ids"]))


def appearances_for(db, op):
    ids = [op.id, *((op.data or {}).get("mirror_ids") or [])]
    return db.scalars(select(m.JobSource).where(m.JobSource.opportunity_id.in_(ids))).all()


def freshness(op, appearances, *, now=None):
    now = aware(now) or utcnow()
    # A disabled monitor does not erase an actual recent observation. Its clock
    # still ages normally; superseded routes cannot establish current liveness.
    current = [x for x in appearances if (x.company_source.config or {}).get("replacement_state") != "superseded"]
    official = [x for x in current if x.company_source.verified]
    observations = official or current
    live = [x for x in observations if x.status == "active"]
    listing = max((aware(x.last_seen) for x in live if x.last_seen), default=None)
    detail = parse_date((op.data or {}).get("description_checked_at"))
    # Legacy records have no promoted-description clock. A same-source full
    # detail observation is usable only when it actually belongs to this JD.
    if detail is None and op.description:
        primary_id = (op.data or {}).get("description_source_id")
        valid = [x for x in observations if x.last_detail_checked and primary_id and x.company_source_id == primary_id]
        detail = max((aware(x.last_detail_checked) for x in valid), default=None)
    reasons = []
    if op.status != "active": reasons.append("Availability needs review; the role is not currently confirmed active.")
    if op.deadline and aware(op.deadline) < now: reasons.append("The published deadline has passed; confirm whether applications remain open.")
    if not listing: reasons.append("A current listing observation is missing.")
    elif listing < now - timedelta(hours=48): reasons.append("The listing has not been seen in the last 48 hours; recheck availability.")
    if not op.description: reasons.append("The full job description has not been collected.")
    elif not detail: reasons.append("The age of the full job description is unknown; recheck the original posting.")
    elif detail < now - timedelta(days=7): reasons.append("The full job description is older than seven days; recheck requirements.")
    if (op.data or {}).get("identity_review"): reasons.append("Historical source identity needs review before recommending this role.")
    return {"listing_seen_at": listing, "detail_checked_at": detail,
            "state": "review" if reasons else "fresh", "reasons": reasons,
            "listing_max_age_hours": 48, "detail_max_age_hours": 168}


def assessment(op, appearances, rules, *, now=None):
    from .search_policy import location_decision
    result = freshness(op, appearances, now=now)
    reasons = list(result["reasons"])
    if hidden(op, rules): reasons.append("This role or company is excluded from your shortlist.")
    if location_decision(op.location, op.country, op.work_mode) != "allowed": reasons.append("Location is outside your confirmed Bengaluru, Chennai or India remote scope.")
    if op.eligibility in {"probably ineligible", "ineligible"}: reasons.append("A mandatory eligibility check conflicts with your confirmed profile facts.")
    if op.risk_reasons: reasons.append("Published risk signals need review.")
    if not canonicalize_url(op.apply_url or op.canonical_url): reasons.append("A usable original application URL has not been established.")
    eligibility_review = op.eligibility not in {"eligible", "probably eligible", "ineligible", "probably ineligible"}
    return {**result, "recommended": not reasons, "recommendation_state": "review eligibility" if not reasons and eligibility_review else "review posting" if reasons else "supported alignment",
            "eligibility_review_required": eligibility_review, "preparation_allowed": not reasons,
            "review_reasons": list(dict.fromkeys(reasons))}


def employer_identity(values, fallback):
    """Actual observed employer, not a parent-group fuzzy-name match."""
    data = values.get("data") or {}
    name = str(data.get("observed_employer") or fallback or "").strip().casefold()
    return re.sub(r"\s+", " ", name)


def explicit_requisition(raw, requisition):
    """Provider's requisition key or labelled ID, never a bare generic job ID."""
    if not requisition: return False
    value = str(requisition).strip()
    if re.fullmatch(r"(?:JR|REQ[-_]?|R[-_])\d[\w-]*|req-[\w-]+", value, re.I): return True
    keys = {"jobreqid", "requisition_id", "requisitionid", "requisitionnumber"}
    if isinstance(raw, dict):
        for key, item in raw.items():
            if str(key).lower() in keys and str(item).strip() == value: return True
            if isinstance(item, (dict, list)) and explicit_requisition(item, value): return True
    elif isinstance(raw, list):
        return any(explicit_requisition(x, value) for x in raw)
    return False


def trusted_requisition(db, op, snapshots=None):
    if not op.requisition_id: return False
    for src in op.sources:
        if not src.company_source.verified or src.requisition_id != op.requisition_id: continue
        snapshot = snapshots.get(src.id) if snapshots is not None else db.scalar(select(m.Snapshot).where(m.Snapshot.job_source_id == src.id).order_by(m.Snapshot.created_at.desc()).limit(1))
        if snapshot and explicit_requisition(snapshot.raw, op.requisition_id): return True
    return False


def proven_mirror(a, b, *, employer_a, employer_b, trusted_a=False, trusted_b=False):
    if not employer_a or employer_a != employer_b: return None
    req_a, req_b = a.get("requisition_id"), b.get("requisition_id")
    if req_a and req_b and str(req_a).casefold() != str(req_b).casefold(): return None
    title_a, title_b = str(a.get("title") or "").strip().casefold(), str(b.get("title") or "").strip().casefold()
    if not title_a or title_a != title_b: return None
    url_a, url_b = canonicalize_url(a.get("canonical_url")), canonicalize_url(b.get("canonical_url"))
    if url_a and url_a == url_b: return "exact_url"
    if req_a and req_b and trusted_a and trusted_b and str(req_a).casefold() == str(req_b).casefold():
        return "exact_requisition"
    return None
