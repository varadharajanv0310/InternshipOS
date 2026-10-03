"""Deterministic, evidence-bearing interpretation. No network or invented facts."""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .db import aware, utcnow

STAGES = {"ready", "applied", "oa", "interview", "offer", "rejected", "withdrawn"}
STAGE_ORDER = {"ready": 0, "applied": 1, "oa": 2, "interview": 3, "offer": 4}
SKILL_ALIASES = {
    "javascript": ["javascript", "js"], "typescript": ["typescript"],
    "python": ["python"], "java": ["java"], "c++": ["c++"], "c#": ["c#"],
    "go": ["golang"], "rust": ["rust"], "sql": ["sql"],
    "postgresql": ["postgresql", "postgres"], "mysql": ["mysql"], "mongodb": ["mongodb"],
    "react": ["react", "react.js", "reactjs"], "node.js": ["node.js", "nodejs"],
    "django": ["django"], "fastapi": ["fastapi"], "flask": ["flask"],
    "pytorch": ["pytorch"], "tensorflow": ["tensorflow"],
    "scikit-learn": ["scikit-learn", "scikit learn", "sklearn"],
    "pandas": ["pandas"], "numpy": ["numpy"], "spark": ["apache spark", "pyspark"],
    "docker": ["docker"], "kubernetes": ["kubernetes", "k8s"],
    "aws": ["aws", "amazon web services"], "azure": ["azure"],
    "gcp": ["gcp", "google cloud"], "git": ["git"], "linux": ["linux"],
    "html": ["html"], "css": ["css"], "excel": ["excel"], "power bi": ["power bi"],
}


def stable_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode()).hexdigest()


def text_only(value: str | None) -> str:
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", value or "", flags=re.I | re.S)
    value = re.sub(r"</(?:p|div|li|h[1-6]|br)>|<br\s*/?>", "\n", value, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()


def canonicalize_url(value: str | None) -> str | None:
    """Keep identity-bearing query keys; discard only known tracking parameters."""
    if not value:
        return None
    try:
        p = urlsplit(value.strip())
        if p.scheme.lower() not in {"http", "https"} or not p.hostname or p.username or p.password:
            return None
        host = p.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith(".localhost"):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        port = p.port
        authority = f"[{host}]" if ":" in host else host
        if port and not ((p.scheme == "https" and port == 443) or (p.scheme == "http" and port == 80)):
            authority += f":{port}"
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"gh_src", "lever-source", "ref", "referrer", "trackingid"}]
        return urlunsplit((p.scheme.lower(), authority, p.path.rstrip("/") or "/", urlencode(sorted(query)), ""))
    except (ValueError, TypeError):
        return None


safe_url = canonicalize_url


def source_identity(source_id: str, external_id: str) -> str:
    return stable_hash([source_id, str(external_id)])


def parse_date(value, *, observed_at=None) -> datetime | None:
    if isinstance(value, datetime):
        return aware(value)
    if not value or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, (float, int)):
        try:
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    value = value.strip()
    try:
        return aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        pass
    # Relative dates are anchored to observation, never to a future display time.
    if observed_at:
        anchor = aware(observed_at)
        if value.lower() in {"today", "posted today"}:
            return anchor.replace(hour=0, minute=0, second=0, microsecond=0)
        match = re.fullmatch(r"(?:posted\s+)?(\d+)\s+days?\s+ago", value, re.I)
        if match:
            return (anchor - timedelta(days=int(match[1]))).replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def normalize_location(value: str | None) -> str:
    value = (value or "").strip()
    value = re.sub(r"\bbangalore\b", "Bengaluru", value, flags=re.I)
    return re.sub(r"\s+", " ", value)


def extract_skills(text: str) -> list[str]:
    low = text.lower()
    return [skill for skill, aliases in SKILL_ALIASES.items()
            if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", low) for alias in aliases)]


def extract_requirements(text: str) -> list[dict]:
    requirements = []
    for raw in re.split(r"[\n.!?]+", text):
        sentence = raw.strip()
        if not sentence:
            continue
        requiredness = "preferred" if re.search(r"\b(preferred|a plus|nice.to.have|desirable)\b", sentence, re.I) else "required"
        if re.search(r"graduat|batch\s+of|class\s+of|passing\s+out", sentence, re.I):
            years = [int(x) for x in re.findall(r"\b20[2-4]\d\b", sentence)]
            if years:
                requirements.append({"type": "graduation_year", "min": min(years), "max": max(years), "evidence": sentence, "requiredness": requiredness})
        cgpa = re.search(r"(?:minimum\s+|at\s+least\s+)?(?:cgpa|gpa)\s*(?:of\s*|[:>=]\s*)?(\d(?:\.\d+)?)\s*(?:/\s*(\d+))?", sentence, re.I)
        if cgpa:
            requirements.append({"type": "cgpa", "min": float(cgpa[1]), "scale": float(cgpa[2]) if cgpa[2] else None, "evidence": sentence, "requiredness": requiredness})
        if re.search(r"\b(bachelor|b[ .]?tech|b[ .]?e\.|master|m[ .]?tech|ph\.?d)\b", sentence, re.I):
            levels = []
            for label, pattern in [("bachelor", r"bachelor|b[ .]?tech|b[ .]?e\."), ("master", r"master|m[ .]?tech"), ("phd", r"ph\.?d")]:
                if re.search(pattern, sentence, re.I):
                    levels.append(label)
            requirements.append({"type": "degree", "alternatives": levels, "evidence": sentence, "requiredness": requiredness})
    return requirements


def classify(text, title="") -> dict:
    body = text_only(str(text or ""))
    joined = f"{title}\n{body}".lower()
    title_low = title.lower()
    if re.search(r"\b(intern|internship|internships)\b", title_low):
        kind = "internship"
    elif re.search(r"\bapprentice(?:ship)?\b", title_low):
        kind = "apprenticeship"
    elif re.search(r"\b(?:graduate|new grad|fresher|entry.level)\b", title_low):
        kind = "graduate"
    elif re.search(r"\b(?:internship|intern position|as an intern)\b", body.lower()) and not re.search(r"\b(?:senior|staff|principal|manager)\b", title_low):
        kind = "possible_internship"
    else:
        kind = "other" if title else "unclear"
    excluded = bool(re.search(r"\b(?:sales|marketing|human resources|hr|content writ|graphic design|business development|mechanical|civil)\b", title_low))
    # Give title higher authority than boilerplate naming every department.
    role = "unclear"
    patterns = [
        ("AI_ML", r"machine learning|artificial intelligence|\bml\b|\bai\b|\bllm\b|\bmlops\b|generative ai|computer vision|\bnlp\b|deep learning"),
        ("Data", r"data scien|data engineer|data analy|analytics engineer|business intelligence|technical analy"),
        ("SWE", r"\b(?:sde|swe)\b|software|developer|frontend|front.end|backend|back.end|full.stack|programmer|web engineer|mobile engineer|(?:web|app|mobile app|ios app|react native|blockchain|\.net) development|automation testing|manual testing|quality analyst"),
        ("Adjacent", r"devops|cloud engineer|security engineer|database engineer|site reliability|\bsre\b|platform engineer"),
    ]
    for corpus in [title_low, body.lower()]:
        for family, pattern in patterns:
            if re.search(pattern, corpus):
                role = family
                break
        if role != "unclear":
            break
    # A company's AI/software boilerplate is not the applicant's role.
    title_technical=any(re.search(pattern,title_low) for _,pattern in patterns)
    if not title_technical and re.search(r'\b(?:ux design(?:er|ing)?|ui design(?:er|ing)?|(?:game|3d|2d|concept|visual) artist|video edit(?:or|ing)?|creative|communications|people team|talent acquisition|accounting|finance|copywrit(?:er|ing)?|recruiter|social media|customer success|customer support|fashion|legal|law|teacher|teaching)\b',title_low):
        excluded=True
    if excluded:
        role = "excluded"
    skills = extract_skills(joined)
    requirements = extract_requirements(body)
    risks = []
    for pattern, reason in [
        (r"(?:pay|payment|deposit|fee).{0,35}(?:registration|training|apply|application|security)|(?:registration|training|application).{0,20}fee", "Posting mentions an application/training fee; verify the exact terms."),
        (r"guaranteed (?:placement|job|income)", "Posting promises guaranteed placement or income."),
        (r"(?:crypto|bitcoin).{0,25}(?:payment|deposit)", "Posting requests cryptocurrency payment or deposit."),
    ]:
        if re.search(pattern, joined):
            risks.append(reason)
    return {"role_family": role, "opportunity_type": kind, "skills": skills, "requirements": requirements,
            "risk_reasons": risks, "trust_state": "review" if risks else "unassessed",
            "summary": re.sub(r"\s+", " ", body)[:360], "confidence": "high" if role not in {"unclear", "excluded"} and kind == "internship" else "limited"}


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _strings(values) -> list[str]:
    if isinstance(values, str):
        return [x.strip().lower() for x in re.split(r"[,;]", values) if x.strip()]
    return [str(x.get("name", x.get("skill", "")) if isinstance(x, dict) else x).lower() for x in (values or [])]


def evaluate(opportunity, profile) -> dict:
    profile = profile or {}
    if "data" in profile and isinstance(profile["data"], dict):
        profile = profile["data"]
    education = profile.get("education") or {}
    if isinstance(education, list):
        education = education[0] if education else {}
    if not isinstance(education, dict):
        education = {"degree": str(education)}
    reqs = _get(opportunity, "requirements", []) or []
    req_skills = _strings(_get(opportunity, "skills", []))
    user_skills = set(_strings(profile.get("skills")))
    user_skills.update(extract_skills(" ".join(user_skills)))
    preferences = profile.get("preferences") or {}
    roles = _strings(profile.get("preferred_roles") or preferences.get("roles"))
    locations = _strings(profile.get("preferred_locations") or preferences.get("locations"))
    checks, unknowns = [], []
    for req in reqs:
        if not isinstance(req, dict):
            continue
        kind, result = req.get("type"), "unknown"
        if kind == "graduation_year":
            year = profile.get("graduation_year") or education.get("graduation_year")
            if not year:
                date = profile.get("graduation_date") or education.get("graduation_date")
                year = re.search(r"20\d\d", str(date or ""))
                year = year[0] if year else None
            try:
                if year:
                    result = "met" if req.get("min", int(year)) <= int(year) <= req.get("max", int(year)) else "not_met"
            except (TypeError, ValueError):
                pass
        elif kind == "cgpa":
            gpa = profile.get("cgpa", education.get("cgpa"))
            scale = profile.get("cgpa_scale", education.get("cgpa_scale"))
            if gpa is not None and scale is not None and req.get("scale") is not None:
                try:
                    if float(scale) == float(req["scale"]):
                        result = "met" if float(gpa) >= float(req["min"]) else "not_met"
                except (TypeError, ValueError):
                    pass
        elif kind == "degree":
            degree = str(profile.get("degree") or education.get("degree") or "").lower()
            if degree:
                level = next((label for label, pattern in [("bachelor", r"bachelor|b\.?\s?tech|b\.?\s?e\b|bsc|bca"), ("master", r"master|m\.?\s?tech|msc|mca"), ("phd", r"ph\.?d")] if re.search(pattern, degree)), None)
                if level:
                    result = "met" if level in req.get("alternatives", []) else "unknown"
        checks.append({**req, "result": result})
        if result == "unknown":
            unknowns.append(f"Eligibility: {kind} needs a confirmed profile fact or clearer requirement.")
    hard = [c for c in checks if c.get("requiredness") != "preferred"]
    if any(c["result"] == "not_met" for c in hard):
        eligibility = "probably ineligible"  # prose-derived rules require review before exclusion
    elif hard and all(c["result"] == "met" for c in hard):
        eligibility = "probably eligible"
    else:
        eligibility = "unclear"
    if not hard:
        unknowns.append("Published eligibility constraints have not been established.")

    dimensions = []
    def dimension(name, weight, ratio, reason):
        known = ratio is not None
        points = round(weight * max(0, min(1, ratio)), 2) if known else None
        dimensions.append({"name": name, "weight": weight, "score": round(ratio * 100) if known else None,
                           "points": points, "lower": points if known else 0, "upper": points if known else weight,
                           "known": known, "reason": reason})
        if not known:
            unknowns.append(reason)
    family = str(_get(opportunity, "role_family", "unclear")).lower()
    role_terms = {"swe": ["software", "swe", "developer"], "data": ["data", "analytics"], "ai_ml": ["ai", "ml", "machine learning"], "adjacent": ["cloud", "devops", "security"]}
    role_ratio = (1.0 if any(any(term in r for term in role_terms.get(family, [family])) for r in roles) else 0.0) if roles and family not in {"unclear", "excluded"} else None
    dimension("Role alignment", 25, role_ratio, "Confirm preferred roles and role classification.")
    dimension("Required skills", 25, len(set(req_skills) & user_skills) / len(set(req_skills)) if req_skills and user_skills else None,
              "Skill mentions are preliminary requirements; confirmed skills/profile evidence is incomplete.")
    preferred = _strings(_get(opportunity, "data", {}).get("preferred_skills", []))
    dimension("Preferred skills", 10, len(set(preferred) & user_skills) / len(set(preferred)) if preferred and user_skills else None,
              "Preferred skill requirements or profile evidence are unknown.")
    projects = profile.get("projects") or []
    project_text = " ".join(json.dumps(p, ensure_ascii=False) if isinstance(p, dict) else str(p) for p in projects)
    project_skills = set(extract_skills(project_text))
    dimension("Project and experience evidence", 20, len(project_skills & set(req_skills)) / len(set(req_skills)) if project_text and req_skills else None,
              "No supported project/experience comparison is available.")
    edu_checks = [c for c in checks if c.get("type") in {"degree", "graduation_year", "cgpa"}]
    edu_ratio = (sum(c["result"] == "met" for c in edu_checks) / len(edu_checks)) if edu_checks and all(c["result"] != "unknown" for c in edu_checks) else None
    dimension("Education alignment", 10, edu_ratio, "Education/cohort requirements need confirmed evidence.")
    loc = normalize_location(_get(opportunity, "location", "")).lower()
    loc_ratio = (1.0 if any(normalize_location(x).lower() in loc for x in locations) else 0.0) if locations and loc else None
    dimension("Location and duration preference", 10, loc_ratio, "Location/availability preferences or job restrictions are unknown.")
    lower = sum(d["lower"] for d in dimensions)
    upper = sum(d["upper"] for d in dimensions)
    coverage = sum(d["weight"] for d in dimensions if d["known"])
    score = round((lower + upper) / 2, 1) if coverage >= 50 else None
    confidence = "high" if coverage >= 90 else "medium" if coverage >= 70 else "low" if coverage else "unassessed"
    worth_dimensions = [{"name": "Fit", "weight": 35, "score": score},
                        {"name": "Substantive learning", "weight": 20, "score": None},
                        {"name": "Availability and location", "weight": 15, "score": round(loc_ratio * 100) if loc_ratio is not None else None},
                        {"name": "Compensation", "weight": 10, "score": None},
                        {"name": "Company and engineering relevance", "weight": 10, "score": None},
                        {"name": "Effort and timing", "weight": 10, "score": None}]
    description = str(_get(opportunity, "description", ""))
    quality_signals = [("Mentorship", r"\bmentor(?:ship)?\b"), ("Defined engineering work", r"\b(?:develop|build|implement|research|test)\b.{0,70}\b(?:software|model|pipeline|application|system|feature)\b"),
                       ("Technical team", r"\b(?:engineering|research|development) team\b")]
    quality_evidence = [label for label, pattern in quality_signals if re.search(pattern, description, re.I)]
    if quality_evidence:
        worth_dimensions[1]["score"] = min(100, 40 + 20 * len(quality_evidence))
        worth_dimensions[1]["evidence"] = quality_evidence
    compensation = _get(opportunity, "compensation", {}) or {}
    minimum_pay = preferences.get("minimum_stipend", profile.get("minimum_stipend"))
    if compensation.get("kind") in {"stated", "employer_stated", "confirmed"}:
        amount = compensation.get("min")
        try:
            if amount is not None and float(amount) == 0:
                worth_dimensions[3]["score"] = 0
            elif amount is not None and minimum_pay is not None and float(minimum_pay) > 0 and str(compensation.get("currency", "")).upper() == "INR" and str(compensation.get("period", "")).lower() in {"month", "monthly"}:
                worth_dimensions[3]["score"] = min(100, 100 * float(amount) / float(minimum_pay))
        except (TypeError, ValueError):
            pass
    company_name = str(_get(_get(opportunity, "company", {}), "name", "")).lower()
    company_preferences = _strings(profile.get("preferred_companies") or preferences.get("companies"))
    if company_name and company_preferences:
        worth_dimensions[4]["score"] = 100 if company_name in company_preferences else 50
    effort = (_get(opportunity, "data", {}) or {}).get("application_effort_minutes")
    if isinstance(effort, (int, float)) and effort >= 0:
        worth_dimensions[5]["score"] = max(0, 100 - effort)
    worth_lower = sum(d["weight"] * d["score"] / 100 for d in worth_dimensions if d["score"] is not None)
    worth_coverage = sum(d["weight"] for d in worth_dimensions if d["score"] is not None)
    worth_upper = worth_lower + 100 - worth_coverage
    worth_score = round((worth_lower + worth_upper) / 2, 1) if worth_coverage >= 50 else None
    for d in worth_dimensions:
        d["known"] = d["score"] is not None
        d["reason"] = "Based on observed/user-confirmed facts; descriptive signal, not a promised outcome." if d["known"] else "Insufficient evidence for this dimension."
    risks = _get(opportunity, "risk_reasons", []) or []
    return {"version": "deterministic-v1", "fit_score": score, "fit_confidence": confidence,
            "fit_lower": round(lower, 1), "fit_upper": round(upper, 1), "evidence_coverage": coverage,
            "worth_score": worth_score, "worth_lower": round(worth_lower, 1), "worth_upper": round(worth_upper, 1),
            "worth_evidence_coverage": worth_coverage, "eligibility": eligibility, "fit_dimensions": dimensions,
            "worth_dimensions": worth_dimensions, "eligibility_checks": checks, "unknowns": list(dict.fromkeys(unknowns)),
            "evidence": [c.get("evidence") for c in checks if c.get("evidence")],
            "action": "review" if risks or eligibility == "probably ineligible" else "review details",
            "explanation": "Scores describe supported alignment, not hiring probability. Unmeasured dimensions remain unknown."}


def transition(application, stage, *, source="user", occurred_at=None):
    if stage not in STAGES:
        raise ValueError(f"Unsupported application stage: {stage}")
    old = application.stage
    if source != "user" and old in {"offer", "rejected", "withdrawn"}:
        return old, False
    if source != "user" and STAGE_ORDER.get(stage, 99) < STAGE_ORDER.get(old, 0):
        return old, False
    application.stage = stage
    if source == "user" and stage == "applied" and application.submitted_at is None:
        application.submitted_at = aware(occurred_at) or utcnow()
    return old, old != stage
