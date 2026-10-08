"""Transactional core services used by HTTP routes and bounded collection jobs."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
import json
import re

from sqlalchemy import func, or_, select, tuple_

from sqlalchemy.orm import joinedload, selectinload
from . import models as m
from .db import aware, utcnow
from .domain import canonicalize_url, classify, evaluate, normalize_location, parse_date, stable_hash, text_only, transition
from .seed import DEFAULT_SETTINGS, EMPTY_PROFILE
from .serialize import activity_dict, application_dict, iso, json_value, opportunity_dict, row_dict, source_dict, task_dict


def _require(db, cls, id):
    value = db.get(cls, id)
    if value is None:
        raise ValueError(f"{cls.__name__} not found")
    return value


def _audit(db, kind, title, entity_type=None, entity_id=None, *, before=None, after=None, data=None):
    item = m.Activity(kind=kind, title=title, entity_type=entity_type, entity_id=entity_id,
                      before=json_value(before), after=json_value(after), data=json_value(data or {}))
    db.add(item)
    return item


def _latest_profile(db):
    return db.scalar(select(m.ProfileVersion).order_by(m.ProfileVersion.created_at.desc(), m.ProfileVersion.id.desc()).limit(1))


def get_profile(db):
    profile = _latest_profile(db)
    return {**EMPTY_PROFILE, **(profile.data if profile else {}), "id": profile.id if profile else None,
            "updated_at": iso(profile.created_at) if profile else None}


def get_settings(db):
    # Internal AI caches and worker tokens share this table; never expose them.
    return {**DEFAULT_SETTINGS, **{r.key: r.value for r in db.scalars(select(m.Setting).where(m.Setting.key.in_(list(DEFAULT_SETTINGS)))).all()}}


def _propagate_cadence(db, values):
    """Settings control managed boards; explicitly overridden boards stay local."""
    keys = {1: "priority_poll_hours", 2: "normal_poll_hours", 3: "longtail_poll_hours"}
    count = 0
    for source in db.scalars(select(m.CompanySource)).all():
        if (source.config or {}).get("cadence_override"):
            continue
        key = "normal_poll_hours" if source.provider.lower() in AGGREGATORS else keys.get(source.priority, "normal_poll_hours")
        if key in values:
            source.cadence_hours = float(values[key])
            count += 1
    return count


def save_settings(db, payload):
    before = get_settings(db)
    values = {k: v for k, v in payload.items() if k in DEFAULT_SETTINGS}
    for key, value in values.items():
        if key in {"roles", "locations"} and (not isinstance(value, list) or not all(isinstance(x, str) for x in value)):
            raise ValueError(f"{key} must be a list of strings")
        if key in {"ai_enabled", "notifications_enabled", "automatic_submission", "personal_target_filter", "personal_location_policy"} and not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        if key == "automatic_submission" and value:
            raise ValueError("Use scoped auto_apply settings with explicit supported providers")
        if key == "auto_apply":
            if not isinstance(value, dict) or not isinstance(value.get("enabled", False), bool) or not isinstance(value.get("providers", []), list):
                raise ValueError("auto_apply needs enabled and a supported provider list")
            if any(p not in {"greenhouse", "lever", "ashby"} for p in value.get("providers", [])):
                raise ValueError("Unsupported automatic submission provider")
            if value.get("enabled") and not value.get("providers"):
                raise ValueError("Select the supported providers you explicitly authorize")
            limit=value.get("daily_limit",5)
            if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=10:raise ValueError("Daily automatic submission limit must be 1 to 10")
            value = {"enabled": value.get("enabled", False), "providers": list(dict.fromkeys(value.get("providers", []))), "daily_limit":limit}
        if key == "theme" and value not in {"system", "light", "dark"}:
            raise ValueError("Invalid theme")
        if key in {"priority_poll_hours", "normal_poll_hours", "longtail_poll_hours", "gmail_poll_minutes", "closure_grace_hours", "saved_detail_refresh_hours"}:
            if isinstance(value, bool) or not isinstance(value, (float, int)) or value <= 0:
                raise ValueError(f"{key} must be positive")
            minimum = {"priority_poll_hours": 6, "normal_poll_hours": 12, "longtail_poll_hours": 24, "gmail_poll_minutes": 30, "closure_grace_hours": 24, "saved_detail_refresh_hours": 6}[key]
            if not minimum <= value <= (1440 if key == "gmail_poll_minutes" else 720):
                raise ValueError(f"{key} is outside the supported scheduling range")
        if key in {"ai_monthly_budget_usd", "minimum_fit"}:
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not 0 <= value <= (100 if key == "minimum_fit" else 3):
                raise ValueError(f"Invalid {key}")
        values[key] = value
        row = db.get(m.Setting, key)
        if row:
            row.value = value
        else:
            db.add(m.Setting(key=key, value=value))
    changed = {k: v for k, v in values.items() if before.get(k) != v}
    cadence_count = _propagate_cadence(db, changed)
    _audit(db, "settings.updated", "Settings updated", "settings", before={k: before[k] for k in values}, after=values,
           data={"cadence_sources_updated": cadence_count})
    db.commit()
    return get_settings(db)


def evaluation_facts(db, profile=None):
    """Join reviewed projects into matching without rewriting profile versions."""
    profile = profile or _latest_profile(db)
    facts = dict(profile.data if profile else {})
    projects = [p for p in facts.get('projects', []) if not isinstance(p, dict) or p.get('approved') is not False]
    for project in db.scalars(select(m.Project).where(m.Project.approved.is_(True)).order_by(m.Project.id)):
        # Never include raw GitHub README claims or Project.data in scoring.
        projects.append({'id': project.id, 'name': project.name, 'url': project.github_url,
                         'technologies': project.technologies, 'bullets': project.approved_bullets,
                         'description': project.description})
    facts['projects'] = projects
    return facts


def refresh_project_matching(db):
    """Refresh visible current candidates; future observations use the same facts."""
    from .shortlist import exclusions, visibility_sql
    from .search_policy import target_sql
    stmt = select(m.Opportunity).where(m.Opportunity.status != 'confirmed_closed',
                                      visibility_sql(m.Opportunity, exclusions(db)))
    if get_settings(db).get('personal_location_policy'):
        stmt = stmt.where(target_sql(m.Opportunity))
    profile = _latest_profile(db)
    facts = evaluation_facts(db, profile)
    ops = db.scalars(stmt).all()
    ids = [op.id for op in ops]
    latest = {}
    if ids:
        ranked = select(m.Evaluation.id,func.row_number().over(partition_by=m.Evaluation.opportunity_id,
            order_by=(m.Evaluation.created_at.desc(),m.Evaluation.id.desc())).label('rn')).where(m.Evaluation.opportunity_id.in_(ids)).subquery()
        latest = {e.opportunity_id:e for e in db.scalars(select(m.Evaluation).join(ranked,m.Evaluation.id==ranked.c.id).where(ranked.c.rn==1))}
    for op in ops:
        _evaluate_and_store(db, op, profile, facts=facts,evaluations=[latest[op.id]] if op.id in latest else [])
    return len(ops)


def _evaluate_and_store(db, opportunity, profile=None, *, evaluations=None, facts=None):
    profile = profile or _latest_profile(db)
    facts = evaluation_facts(db, profile) if facts is None else facts
    inputs = {"title": opportunity.title, "role_family": opportunity.role_family, "description": opportunity.description, "skills": opportunity.skills,
              "requirements": opportunity.requirements, "location": opportunity.location,
              "compensation": opportunity.compensation, "risk_reasons": opportunity.risk_reasons,
              "profile": facts, "version": "deterministic-v2"}
    digest = stable_hash(inputs)
    existing = next((e for e in evaluations if e.input_hash == digest), None) if evaluations is not None else db.scalar(select(m.Evaluation).where(m.Evaluation.opportunity_id == opportunity.id, m.Evaluation.input_hash == digest).order_by(m.Evaluation.created_at.desc()).limit(1))
    result = existing.data if existing else evaluate(opportunity, facts)
    latest = evaluations[0] if evaluations else None if evaluations is not None else db.scalar(select(m.Evaluation).where(m.Evaluation.opportunity_id == opportunity.id).order_by(m.Evaluation.created_at.desc()).limit(1))
    if not latest or latest.input_hash != digest or latest.profile_version_id != (profile.id if profile else None):
        db.add(m.Evaluation(opportunity_id=opportunity.id, profile_version_id=profile.id if profile else None, input_hash=digest, version="deterministic-v2", data=result))
    opportunity.fit_score = result["fit_score"]
    opportunity.fit_confidence = result["fit_confidence"]
    opportunity.worth_score = result["worth_score"]
    opportunity.eligibility = result["eligibility"]
    opportunity.data = {**(opportunity.data or {}), "eligibility_summary": {
        "checks": result.get("eligibility_checks", []), "reasons": result.get("eligibility_reasons", []),
        "profile_version_id": profile.id if profile else None}}
    return result


def save_profile(db, payload):
    previous = _latest_profile(db)
    before = previous.data if previous else EMPTY_PROFILE.copy()
    clean = {k: v for k, v in payload.items() if k not in {"id", "updated_at", "created_at"}}
    for key in {"skills", "preferred_roles", "preferred_locations", "projects"}:
        if key in clean and not isinstance(clean[key], list):
            raise ValueError(f"{key} must be a list")
    data = json_value({**before, **clean})
    if data == before:
        return get_profile(db)
    version = m.ProfileVersion(data=data)
    db.add(version)
    db.flush()
    _audit(db, "profile.updated", "Profile facts updated", "profile", version.id, before=before, after=data)
    facts = evaluation_facts(db, version)
    for opportunity in db.scalars(select(m.Opportunity).where(m.Opportunity.status != "confirmed_closed")).yield_per(100):
        _evaluate_and_store(db, opportunity, version, facts=facts)
    db.commit()
    return get_profile(db)


def list_opportunities(db, **filters):
    from .shortlist import exclusions, visibility_sql
    settings=get_settings(db)
    page = max(1, int(filters.get("page") or 1))
    page_size = min(200, max(1, int(filters.get("page_size") or 40)))
    stmt = select(m.Opportunity).join(m.Company)
    rules = exclusions(db)
    visible = visibility_sql(m.Opportunity, rules)
    stmt = stmt.where((m.Opportunity.id.in_(rules["opportunity_ids"]) | m.Opportunity.company_id.in_(rules["company_ids"])) & m.Opportunity.data["duplicate_of"].as_string().is_(None) if filters.get("excluded") else visible)
    if settings.get("personal_location_policy"):
        from .search_policy import target_sql,PHD_ONLY,sql_pattern
        stmt=stmt.where(target_sql(m.Opportunity),~func.lower(m.Opportunity.title).regexp_match(sql_pattern(PHD_ONLY)),m.Opportunity.eligibility!="probably ineligible")
    if filters.get("technical"):
        settings=get_settings(db)
        stmt = stmt.where(m.Opportunity.role_family.in_(settings.get('roles') or ["SWE", "Data", "AI_ML", "Adjacent"]))
        if settings.get('personal_target_filter'):
            from .search_policy import TITLE_EXCLUSIONS,sql_pattern
            stmt=stmt.where(~func.lower(m.Opportunity.title).regexp_match(sql_pattern(TITLE_EXCLUSIONS)))
    for field in ("work_mode", "eligibility"):
        if filters.get(field):
            value = {"eligible": "probably eligible", "ineligible": "probably ineligible"}.get(filters[field], filters[field]) if field == "eligibility" else filters[field]
            stmt = stmt.where(getattr(m.Opportunity,field)==value)
    if filters.get("source"):
        stmt = stmt.where(m.Opportunity.id.in_(select(m.JobSource.opportunity_id).join(m.CompanySource).where(m.CompanySource.provider==filters["source"])))
    if filters.get("fresh_days") is not None:
        stmt = stmt.where(m.Opportunity.first_seen>=utcnow()-timedelta(days=max(1,min(int(filters["fresh_days"]),365))))
    if filters.get("application_stage"):
        stages=select(m.Application.opportunity_id)
        stmt=stmt.where(m.Opportunity.id.not_in(stages) if filters["application_stage"]=="none" else m.Opportunity.id.in_(stages.where(m.Application.stage==filters["application_stage"])))
    if filters.get("min_worth") is not None:
        stmt=stmt.where(m.Opportunity.worth_score>=float(filters["min_worth"]))
    if filters.get("pay"):
        kind=m.Opportunity.compensation["kind"].as_string()
        known=kind.in_(["employer_stated","source_reported","user_reported","historical","unpaid"])
        if filters["pay"]=="known":stmt=stmt.where(known)
        elif filters["pay"]=="unknown":stmt=stmt.where(or_(~known,kind.is_(None)))
        elif filters["pay"]=="unpaid":stmt=stmt.where(or_(kind=="unpaid",func.lower(m.Opportunity.compensation["label"].as_string()).like("%unpaid%")))
    if filters.get("risk"):
        from sqlalchemy import cast,String
        risk_text=cast(m.Opportunity.risk_reasons,String)
        has_risk=risk_text.notin_(["[]","null"])
        high=or_(risk_text.like("%requests cryptocurrency payment%"),m.Opportunity.trust_state=="high_risk")
        official=m.Opportunity.id.in_(select(m.JobSource.opportunity_id).join(m.CompanySource).where(m.CompanySource.verified.is_(True)))
        conditions={"high_risk":high,"verified":~has_risk&m.Company.verified.is_(True)&official,"no_obvious_concern":~has_risk&m.Company.verified.is_(True)&~official,"needs_review":~high&(has_risk|m.Company.verified.is_(False))}
        if filters["risk"] in conditions:stmt=stmt.where(conditions[filters["risk"]])
    q = str(filters.get("q") or "").strip()
    if q:
        pattern = "%" + q.replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(or_(m.Opportunity.title.ilike(pattern, escape="\\"), m.Company.name.ilike(pattern, escape="\\"),
                             m.Opportunity.description.ilike(pattern, escape="\\"), m.Opportunity.requisition_id.ilike(pattern, escape="\\")))
    role = filters.get("role") or filters.get("role_family")
    if role and role != "all":
        stmt = stmt.where(m.Opportunity.role_family == role)
    kind = filters.get("kind") or filters.get("opportunity_type")
    if kind and kind != "all":
        stmt = stmt.where(m.Opportunity.opportunity_type.in_(["internship", "possible_internship"]) if kind == "internship" else m.Opportunity.opportunity_type == kind)
    if filters.get("location"):
        location = normalize_location(str(filters["location"]))
        if location.lower() == "india":
            # Word boundaries prevent Indiana/Indianapolis matching India.
            cities = "india|bengaluru|bangalore|chennai|hyderabad|mumbai|pune|delhi|noida|gurugram|gurgaon|ahmedabad|kolkata|coimbatore|kochi|thiruvananthapuram|mysuru|mangaluru|trivandrum|chandigarh|jaipur|indore"
            stmt = stmt.where(or_(func.lower(m.Opportunity.country).in_(["in", "ind", "india"]), func.lower(m.Opportunity.location).regexp_match(r"(^|[^a-z])(" + cities + r")([^a-z]|$)")))
        else:
            stmt = stmt.where(m.Opportunity.location.ilike("%" + location + "%"))
    if filters.get("company_id"):
        stmt = stmt.where(m.Opportunity.company_id == filters["company_id"])
    if filters.get("saved") is not None and filters.get("saved") != "":
        value = filters["saved"] if isinstance(filters["saved"], bool) else str(filters["saved"]).lower() in {"1", "true", "yes"}
        stmt = stmt.where(m.Opportunity.saved.is_(value))
    if filters.get("status"):
        stmt = stmt.where(m.Opportunity.status == filters["status"])
    if filters.get("min_fit") is not None and float(filters["min_fit"]) > 0:
        stmt = stmt.where(m.Opportunity.fit_score >= float(filters["min_fit"]))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sort = filters.get("sort") or settings.get("default_sort","company_priority")
    order = {"fit": m.Opportunity.fit_score.desc().nullslast(), "worth": m.Opportunity.worth_score.desc().nullslast(),
             "deadline": m.Opportunity.deadline.asc().nullslast(), "company": m.Company.name.asc(),
             "oldest": m.Opportunity.first_seen.asc()}.get(sort, m.Opportunity.first_seen.desc())
    orders=[order]
    if sort=="company_priority":orders=[func.coalesce(m.Company.metadata_json["company_priority"]["score"].as_integer(),30).desc(),m.Opportunity.fit_score.desc().nullslast(),m.Opportunity.first_seen.desc()]
    objects = db.scalars(stmt.options(joinedload(m.Opportunity.company),selectinload(m.Opportunity.sources).joinedload(m.JobSource.company_source)).order_by(*orders, m.Opportunity.id).offset((page - 1) * page_size).limit(page_size)).all()
    base = stmt.subquery()
    facets = {}
    for key in ["role_family", "opportunity_type", "location", "status"]:
        column = base.c[key]
        facets[key] = [{"name": name or "unknown", "count": count} for name, count in db.execute(select(column, func.count()).group_by(column).order_by(func.count().desc()).limit(40))]
    return {"items": [opportunity_dict(db, obj, detail=False, rules=rules) for obj in objects], "total": total, "page": page, "page_size": page_size, "facets": facets}


def get_opportunity(db, id):
    return opportunity_dict(db, db.get(m.Opportunity, id))


def save_opportunity(db, id, payload):
    obj = _require(db, m.Opportunity, id)
    values = {k: v for k, v in payload.items() if k in {"saved", "notes"}}
    if "saved" in values and not isinstance(values["saved"], bool):
        raise ValueError("saved must be true or false")
    if "notes" in values:
        values["notes"] = str(values["notes"] or "")[:50000]
    before = {k: getattr(obj, k) for k in values}
    for key, value in values.items():
        setattr(obj, key, value)
    _audit(db, "opportunity.updated", f"Updated {obj.title}", "opportunity", obj.id, before=before, after=values)
    db.commit()
    return opportunity_dict(db, obj)


def get_shortlist_exclusions(db):
    from .shortlist import exclusions
    rules = exclusions(db)
    return {**rules, "opportunities": [{"id": o.id, "title": o.title, "company": o.company.name} for o in db.scalars(select(m.Opportunity).where(m.Opportunity.id.in_(rules["opportunity_ids"])))],
            "companies": [{"id": c.id, "name": c.name} for c in db.scalars(select(m.Company).where(m.Company.id.in_(rules["company_ids"])))]}


def set_shortlist_exclusion(db, payload):
    from .shortlist import EXCLUSIONS_KEY, exclusions
    kind, id = payload.get("kind"), str(payload.get("id") or "")
    if kind not in {"opportunity", "company"} or not isinstance(payload.get("excluded"), bool):
        raise ValueError("Specify a role or company and whether it is excluded.")
    obj = _require(db, m.Opportunity if kind == "opportunity" else m.Company, id)
    before = exclusions(db)
    values = {k: list(v) for k, v in before.items()}
    key = "opportunity_ids" if kind == "opportunity" else "company_ids"
    values[key] = list(dict.fromkeys([*values[key], id])) if payload["excluded"] else [x for x in values[key] if x != id]
    row = db.get(m.Setting, EXCLUSIONS_KEY)
    if row: row.value = values
    else: db.add(m.Setting(key=EXCLUSIONS_KEY, value=values))
    _audit(db, "shortlist.exclusion", ("Excluded " if payload["excluded"] else "Restored ") + (obj.title if kind == "opportunity" else obj.name), kind, id,
           data={"excluded": payload["excluded"], "previous_rules": before, "rules": values})
    db.commit()
    return get_shortlist_exclusions(db)


def list_companies(db, q=""):
    stmt = select(m.Company).where(m.Company.metadata_json["source_holder"].as_boolean().is_not(True))
    if q:
        stmt = stmt.where(or_(m.Company.name.ilike(f"%{q}%"), m.Company.domain.ilike(f"%{q}%")))
    companies = db.scalars(stmt.order_by(m.Company.name)).all()
    counts = dict(db.execute(select(m.Opportunity.company_id, func.count()).where(m.Opportunity.status == "active").group_by(m.Opportunity.company_id)).all())
    return {"items": [{**row_dict(c), "sources": [source_dict(s) for s in c.sources], "active_opportunities": counts.get(c.id, 0)} for c in companies], "total": len(companies)}


def company_detail(db, id):
    c = db.get(m.Company, id)
    if not c or (c.metadata_json or {}).get("source_holder"):
        return None
    result = row_dict(c)
    result["sources"] = [source_dict(s) for s in c.sources]
    result["opportunities"] = list_opportunities(db, company_id=id, page_size=100)["items"]
    result["applications"] = [application_dict(db, x) for x in db.scalars(select(m.Application).join(m.Opportunity).where(m.Opportunity.company_id == id)).all()]
    return result


def list_applications(db):
    items = db.scalars(select(m.Application).order_by(m.Application.updated_at.desc())).all()
    return {"items": [application_dict(db, x) for x in items], "total": len(items)}


def create_application(db, payload):
    opportunity = _require(db, m.Opportunity, payload.get("opportunity_id"))
    if payload.get("stage","ready")=="ready" and get_settings(db).get("personal_location_policy") and not _personal_scope(opportunity):raise ValueError("This role is outside your location or eligibility policy.")
    attempt = max(1, int(payload.get("attempt", 1)))
    existing = db.scalar(select(m.Application).where(m.Application.opportunity_id == opportunity.id, m.Application.attempt == attempt))
    if existing:
        return application_dict(db, existing)
    if payload.get("stage", "ready") == "ready":
        from .shortlist import assessment, exclusions
        check = assessment(opportunity, opportunity.sources, exclusions(db))
        if not check["preparation_allowed"]:
            raise ValueError("Review this role before preparing: " + " ".join(check["review_reasons"]))
    resume_id = payload.get("resume_version_id") or None
    if resume_id:
        _require(db, m.ResumeVersion, resume_id)
    app = m.Application(opportunity_id=opportunity.id, stage="ready", attempt=attempt, resume_version_id=resume_id, notes=str(payload.get("notes") or ""))
    db.add(app)
    db.flush()
    stage = payload.get("stage", "ready")
    transition(app, stage, source="user", occurred_at=parse_date(payload.get("submitted_at")))
    db.add(m.ApplicationEvent(application_id=app.id, event_type="created", to_stage=stage, source="user", data={"explicit_submission": stage == "applied"}))
    _audit(db, "application.created", f"Application started: {opportunity.title}", "application", app.id, data={"stage": stage})
    db.commit()
    return application_dict(db, app)


def update_application(db, id, payload):
    app = _require(db, m.Application, id)
    before = {"stage": app.stage, "resume_version_id": app.resume_version_id, "notes": app.notes, "submitted_at": iso(app.submitted_at)}
    source = str(payload.get("source", "user"))
    key = payload.get("dedupe_key")
    if key and db.scalar(select(m.ApplicationEvent.id).where(m.ApplicationEvent.application_id == id, m.ApplicationEvent.dedupe_key == key)):
        return application_dict(db, app)
    if "stage" in payload:
        old, changed = transition(app, payload["stage"], source=source, occurred_at=parse_date(payload.get("occurred_at")))
        db.add(m.ApplicationEvent(application_id=id, event_type=payload.get("event_type", "stage_changed"),
                                  from_stage=old, to_stage=app.stage, source=source, dedupe_key=key,
                                  occurred_at=parse_date(payload.get("occurred_at")) or utcnow(),
                                  data={"requested_stage": payload["stage"], "changed": changed, "evidence": payload.get("evidence")}))
    if "notes" in payload:
        app.notes = str(payload["notes"] or "")
    if "resume_version_id" in payload:
        if payload["resume_version_id"]:
            _require(db, m.ResumeVersion, payload["resume_version_id"])
        app.resume_version_id = payload["resume_version_id"] or None
    after = {"stage": app.stage, "resume_version_id": app.resume_version_id, "notes": app.notes, "submitted_at": iso(app.submitted_at)}
    _audit(db, "application.updated", f"Application {app.stage}: {app.opportunity.title}", "application", id, before=before, after=after, data={"source": source})
    db.commit()
    return application_dict(db, app)


def list_tasks(db):
    tasks = db.scalars(select(m.Task).order_by(m.Task.completed, m.Task.due_at.asc().nullslast(), m.Task.created_at.desc())).all()
    return {"items": [task_dict(t) for t in tasks], "total": len(tasks)}


def save_task(db, payload, id=None):
    task = _require(db, m.Task, id) if id else None
    if not task and payload.get("dedupe_key"):
        task = db.scalar(select(m.Task).where(m.Task.dedupe_key == payload["dedupe_key"]))
    before = row_dict(task) if task else None
    if not task:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("Task title is required")
        task = m.Task(title=title[:1000])
        db.add(task)
    for key in ["title", "notes", "kind", "date_precision", "dedupe_key"]:
        if key in payload:
            setattr(task, key, str(payload[key] or ""))
    if "completed" in payload:
        if not isinstance(payload["completed"], bool):
            raise ValueError("completed must be true or false")
        task.completed = payload["completed"]
    for key, cls in [("application_id", m.Application), ("opportunity_id", m.Opportunity)]:
        if key in payload:
            if payload[key]:
                _require(db, cls, payload[key])
            setattr(task, key, payload[key] or None)
    if "due_at" in payload:
        task.due_at = parse_date(payload["due_at"])
        if payload["due_at"] and task.due_at is None:
            raise ValueError("due_at must be an ISO date or timestamp")
        task.date_precision = payload.get("date_precision", "date" if len(str(payload["due_at"])) == 10 else "timestamp" if task.due_at else "unknown")
    if "data" in payload:
        task.data = json_value(payload["data"])
    db.flush()
    after = row_dict(task)
    _audit(db, "task.updated" if before else "task.created", task.title, "task", task.id, before=before, after=after)
    db.commit()
    return task_dict(task)


def list_activity(db):
    total = db.scalar(select(func.count()).select_from(m.Activity)) or 0
    items = db.scalars(select(m.Activity).order_by(m.Activity.created_at.desc()).limit(500)).all()
    return {"items": [activity_dict(x) for x in items], "total": total}


def undo_activity(db, id):
    activity = _require(db, m.Activity, id)
    if activity.undone_at:
        return activity_dict(activity)
    if activity.before is None:
        raise ValueError("This event records evidence or creation and cannot be undone destructively")
    kind = activity.entity_type
    if kind in {"opportunity", "application", "task"}:
        cls = {"opportunity": m.Opportunity, "application": m.Application, "task": m.Task}[kind]
        obj = _require(db, cls, activity.entity_id)
        keys = [k for k in activity.before if k not in {"id", "created_at", "updated_at"}]
        if any(json_value(getattr(obj, k)) != activity.after.get(k) for k in keys):
            raise ValueError("A newer edit conflicts with this undo; review the current record")
        old_stage = getattr(obj, "stage", None)
        for key in keys:
            value = activity.before[key]
            if key.endswith("_at") and value:
                value = parse_date(value)
            setattr(obj, key, value)
        if kind == "application":
            db.add(m.ApplicationEvent(application_id=obj.id, event_type="manual_correction", source="user", from_stage=old_stage, to_stage=obj.stage, data={"undo_activity_id": id}))
            if activity.kind == "email_match":
                for task_id in activity.data.get("created_task_ids", []):
                    task = db.get(m.Task, task_id)
                    if task:
                        # Retain the historical task and cancel its future reminder.
                        task.completed = True
                        task.data = {**task.data, "cancelled": True, "undo_email_activity_id": id}
                for previous in activity.data.get("cancelled_tasks", []):
                    task = db.get(m.Task, previous["id"])
                    if task and task.data.get("email_id") == activity.data.get("email_id"):
                        task.completed = previous["completed"]
                        task.data = previous["data"]
                email = db.get(m.EmailMessage, activity.data.get("email_id"))
                if email:
                    email.status = "review"
                    email.data = {**email.data, "undone_activity_id": id}
                    for link in db.scalars(select(m.EmailLink).where(m.EmailLink.email_message_id == email.id, m.EmailLink.application_id == obj.id, m.EmailLink.event_type == activity.data.get("event_type"))).all():
                        link.data = {**link.data, "undone": True}
    elif kind == "settings":
        current = get_settings(db)
        if any(current.get(k) != v for k, v in activity.after.items()):
            raise ValueError("Settings changed after this event")
        for key, value in activity.before.items():
            row = db.get(m.Setting, key)
            if row:
                row.value = value
            else:
                db.add(m.Setting(key=key, value=value))
        _propagate_cadence(db, activity.before)
    elif kind == "profile":
        current = _latest_profile(db)
        if not current or current.data != activity.after:
            raise ValueError("Profile changed after this event")
        new = m.ProfileVersion(data=activity.before)
        db.add(new)
        db.flush()
        for opportunity in db.scalars(select(m.Opportunity).where(m.Opportunity.status != "confirmed_closed")).all():
            _evaluate_and_store(db, opportunity, new)
    else:
        raise ValueError("This event is not reversible")
    activity.undone_at = utcnow()
    _audit(db, "activity.undone", f"Undid: {activity.title}", kind, activity.entity_id, data={"original_activity_id": id})
    db.commit()
    return activity_dict(activity)


AGGREGATORS = {"freehire", "unstop", "jobspy", "linkedin", "indeed", "naukri", "google_jobs", "google", "wellfound", "internshala", "cutshort"}


def _employer_for_job(db, source, job, preferred=None):
    """A global feed owns the observation, never all employers in that feed."""
    from urllib.parse import urlsplit
    name = str(job.get("company_name") or "").strip()
    domain = str(job.get("company_domain") or "").strip().lower()
    if domain:
        domain = urlsplit(domain if "://" in domain else "https://" + domain).hostname or ""
        if domain.startswith("www."):
            domain = domain[4:]
    aggregate = source.provider.lower() in AGGREGATORS or bool((source.config or {}).get("global_feed"))
    if not aggregate:
        return source.company
    if not name and not domain:
        raise ValueError("Aggregator record lacks employer identity")
    name = name or domain
    if preferred is not None:
        # A later discovery pass must not pick a different same-named Company
        # merely because an official/candidate row was added after ingestion.
        # Preserve the stable appearance only for an exact name/declared alias
        # and no conflicting domain claim. Actual identity changes still fail.
        exact_names={str(x).strip().casefold() for x in [preferred.name,*list(preferred.aliases or [])]}
        existing_domain=(preferred.domain or '').lower().removeprefix('www.')
        if name.casefold() in exact_names and (not domain or not existing_domain or domain==existing_domain):
            return preferred
    company = None
    if domain:
        # Domain evidence narrows identity; conflicting domains must not name-merge.
        company = db.scalar(select(m.Company).where(func.lower(m.Company.domain) == domain).limit(1))
    if company is None:
        candidates = db.scalars(select(m.Company).where(func.lower(m.Company.name) == name.lower())).all()
        company = next((c for c in candidates if not domain or not c.domain or c.domain.lower().removeprefix("www.") == domain), None)
    if company is None:
        from .company_priority import default_priority
        company = m.Company(name=name[:300], domain=domain or None, verified=False,
                            metadata_json={"discovery_source_id": source.id, "verification_status": "candidate",
                                           "company_priority": default_priority(name),
                                           "evidence_url": job.get("canonical_url") or job.get("apply_url"),
                                           "observed_name": name, "domain_claim": domain or None})
        db.add(company)
        db.flush()
        _audit(db, "company.discovered", f"New employer candidate: {name}", "company", company.id,
               data={"source_id": source.id, "association": "unverified"})
    return company


def _normalize_job(job, now):
    title = text_only(str(job.get("title") or "")).strip()
    if not title:
        raise ValueError("Missing job title")
    url = canonicalize_url(job.get("canonical_url") or job.get("apply_url"))
    external_id = str(job.get("external_id") or "").strip()
    if not external_id and url:
        external_id = "url:" + stable_hash(url)
    if not external_id:
        raise ValueError("Missing stable external ID and usable URL")
    description = text_only(job.get("description") or job.get("description_html") or "")
    interpreted = classify(description, title)
    employment = str(job.get("employment_type") or "").lower()
    if interpreted["opportunity_type"] == "other" and re.search(r"\bintern(?:ship)?\b", employment):
        interpreted["opportunity_type"] = "internship"
    skills = job.get("skills") or interpreted["skills"]
    if isinstance(skills, str):
        skills = [x.strip() for x in re.split(r"[,;]", skills) if x.strip()]
    pay = job.get("compensation") if isinstance(job.get("compensation"), dict) else {}
    return {"external_id": external_id[:700], "title": title[:800], "description": description,
            "description_html": str(job.get("description_html") or ""),
            "location": normalize_location(str(job.get("location") or ""))[:800],
            "country": str(job["country"])[:120] if job.get("country") else None,
            "work_mode": str(job.get("work_mode") or "unknown"), "compensation": json_value(pay),
            "skills": json_value(skills), "requirements": job.get("requirements") or interpreted["requirements"],
            "responsibilities": job.get("responsibilities") or [], "role_family": interpreted["role_family"],
            "opportunity_type": interpreted["opportunity_type"], "risk_reasons": interpreted["risk_reasons"],
            "summary": interpreted["summary"], "trust_state": interpreted["trust_state"],
            "canonical_url": url, "apply_url": canonicalize_url(job.get("apply_url")) or url,
            "requisition_id": str(job["requisition_id"])[:300] if job.get("requisition_id") else None,
            "posted_at": parse_date(job.get("posted_at"), observed_at=now), "deadline": parse_date(job.get("deadline")),
            "data": {"employment_type": job.get("employment_type"), "posted_raw": json_value(job.get("posted_at")),
                     "observed_employer": job.get("company_name"),
                     "deadline_raw": json_value(job.get("deadline")), "deadline_precision": "date" if len(str(job.get("deadline") or "")) == 10 else "timestamp" if parse_date(job.get("deadline")) else "unknown",
                     "source_evidence": json_value(job.get("evidence") or []), "preferred_skills": job.get("preferred_skills") or []}}


def reconcile_availability(db, opportunity):
    appearances = db.scalars(select(m.JobSource).where(m.JobSource.opportunity_id == opportunity.id, m.JobSource.status != 'historical_alias')).all()
    current = [x for x in appearances if (x.company_source.config or {}).get('replacement_state') != 'superseded']
    authoritative = [x for x in current if x.company_source.verified]
    states = [x.status for x in authoritative or current]
    if 'active' in states:
        opportunity.status = 'active'
    elif states and all(x == 'confirmed_closed' for x in states):
        opportunity.status = 'confirmed_closed'
    elif 'possibly_closed' in states:
        opportunity.status = 'possibly_closed'
    elif appearances and not current and opportunity.status != 'confirmed_closed':
        opportunity.status = 'needs_recheck'


def ingest_batch(db, company_source_id, jobs, *, complete, error=None, coverage_scope="full", observed_count=None, inventory_ids=None, inventory_complete=None, collection_metadata=None):
    """One atomic observation batch. An incomplete result never advances absence.

    Source rows are locked on Postgres to serialize concurrent scans of one board.
    Exact natural IDs or non-conflicting canonical URLs may associate appearances;
    fuzzy similarity only records review candidates, never destructive merges.
    """
    source = db.scalar(select(m.CompanySource).where(m.CompanySource.id == company_source_id).with_for_update().execution_options(populate_existing=True))
    if not source:
        raise ValueError("CompanySource not found")
    now = utcnow()
    run = m.FetchRun(company_source_id=source.id, coverage_scope=str(coverage_scope), complete=False,
                     observed_count=int(observed_count if observed_count is not None else len(jobs)), status="running", error=str(error)[:4000] if error else None)
    db.add(run)
    db.flush()
    existing = {x.external_id: x for x in db.scalars(select(m.JobSource).where(m.JobSource.company_source_id == source.id)).all()}
    seen, touched, issues = set(), set(), []
    stats = {"created": 0, "updated": 0, "unchanged": 0, "reopened": 0, "invalid": 0, "possibly_closed": 0, "closed": 0}
    profile = _latest_profile(db)
    facts = evaluation_facts(db, profile)
    for raw_job in jobs:
        try:
            if not isinstance(raw_job, dict):
                raise ValueError("Record is not an object")
            values = _normalize_job(raw_job, now)
            external_id = values.pop("external_id")
            if external_id in seen:
                continue
            appearance = existing.get(external_id)
            employer = _employer_for_job(db, source, raw_job,preferred=appearance.opportunity.company if appearance else None)
            if appearance and appearance.requisition_id and values["requisition_id"] and appearance.requisition_id != values["requisition_id"]:
                raise ValueError("Stable external ID changed trusted requisition; quarantined for identity review")
            if appearance and appearance.opportunity.company_id != employer.id:
                raise ValueError("Stable external ID changed employer; quarantined for identity review")
            seen.add(external_id)
            digest = stable_hash(json_value(values))
            opportunity = appearance.opportunity if appearance else None
            associated = False
            if opportunity is None and values["canonical_url"] and values["canonical_url"] != canonicalize_url(source.url):
                candidates = db.scalars(select(m.Opportunity).where(m.Opportunity.company_id == employer.id,
                                                                     m.Opportunity.canonical_url == values["canonical_url"])).all()
                for candidate in candidates:
                    if candidate.requisition_id and values["requisition_id"] and candidate.requisition_id != values["requisition_id"]:
                        continue
                    # Identical landing/application endpoints with conflicting titles are not identity.
                    from .shortlist import employer_identity
                    if (candidate.title.casefold().strip() == values["title"].casefold().strip()
                        and employer_identity({"data": candidate.data}, employer.name) == employer_identity(values, employer.name)):
                        opportunity, associated = candidate, True
                        break
            association_reason = "exact_url" if associated else None
            if opportunity is None and values["requisition_id"] and source.verified:
                from .shortlist import employer_identity, proven_mirror, trusted_requisition, explicit_requisition
                for candidate in db.scalars(select(m.Opportunity).where(m.Opportunity.company_id == employer.id, m.Opportunity.requisition_id == values["requisition_id"], m.Opportunity.data["duplicate_of"].as_string().is_(None))).all():
                    if any(x.company_source_id == source.id for x in candidate.sources):
                        continue  # Distinct postings within one board stay distinct.
                    proof = proven_mirror(row_dict(candidate), values, employer_a=employer_identity({"data": candidate.data}, employer.name),
                                          employer_b=employer_identity(values, employer.name),
                                          trusted_a=trusted_requisition(db, candidate), trusted_b=explicit_requisition(raw_job.get("raw") or raw_job, values["requisition_id"]))
                    if proof:
                        opportunity, associated, association_reason = candidate, True, proof
                        break
            created = opportunity is None
            if created:
                opportunity = m.Opportunity(company_id=employer.id, title=values["title"], first_seen=now)
                db.add(opportunity)
                db.flush()
                stats["created"] += 1
                # Preserve possible duplicates while keeping different requisitions separate.
                for candidate in db.scalars(select(m.Opportunity).where(m.Opportunity.company_id == employer.id,
                                                                        func.lower(m.Opportunity.title) == values["title"].lower(),
                                                                        m.Opportunity.id != opportunity.id).limit(12)).all():
                    different = bool(candidate.requisition_id and values["requisition_id"] and candidate.requisition_id != values["requisition_id"])
                    db.add(m.IdentityDecision(opportunity_id=opportunity.id, candidate_id=candidate.id,
                                              decision="distinct" if different else "possible",
                                              evidence={"reason": "different trusted requisitions" if different else "same employer and title; identity not proven",
                                                        "requisitions": [candidate.requisition_id, values["requisition_id"]]}))
            if appearance is None:
                appearance = m.JobSource(company_source_id=source.id, opportunity_id=opportunity.id, external_id=external_id,
                                         requisition_id=values["requisition_id"], url=values["canonical_url"], first_seen=now, last_seen=now)
                db.add(appearance)
                db.flush()
                existing[external_id] = appearance
                if associated:
                    db.add(m.IdentityDecision(opportunity_id=opportunity.id, job_source_id=appearance.id, decision=association_reason or "exact_url",
                                              evidence={"canonical_url": values["canonical_url"], "reversible_source_link": True,
                                                        "company_id": employer.id, "requisition_id": values["requisition_id"]}))
            if not values['description'] and opportunity.description:
                # Sparse listings must retain conclusions grounded in the cached
                # JD. This does not refresh the description's observation clock.
                retained = classify(opportunity.description,values['title'])
                for field in ('role_family','opportunity_type','risk_reasons','summary','trust_state'):
                    values[field]=retained[field]
                if not raw_job.get('requirements'):
                    values['requirements']=retained['requirements']
                digest=stable_hash(json_value(values))
            old_status = appearance.status
            appearance.last_seen = now
            appearance.missed_complete_runs = 0
            appearance.first_missing_at = None
            appearance.status = "active"
            if values["description"]:
                # Checking an unchanged description still refreshes its liveness.
                appearance.last_detail_checked = now
                if values["description"] == opportunity.description and (source.verified or not any(x.company_source.verified for x in opportunity.sources)):
                    opportunity.data = {**(opportunity.data or {}), "description_checked_at": iso(now), "description_source_id": source.id}
            appearance.url = values["canonical_url"] or appearance.url
            appearance.requisition_id = values["requisition_id"] or appearance.requisition_id
            opportunity.last_verified = now
            opportunity.status = "active"
            if old_status in {"possibly_closed", "confirmed_closed"}:
                stats["reopened"] += 1
                _audit(db, "opportunity.reopened", f"Available again: {opportunity.title}", "opportunity", opportunity.id, data={"source_id": source.id})
            changed = appearance.latest_hash != digest
            if changed:
                # A sparse listing refresh must not erase a richer detail observation.
                old_values = {key: json_value(getattr(opportunity, key)) for key in values}
                authority_other = db.scalar(select(m.JobSource.id).join(m.CompanySource).where(m.JobSource.opportunity_id == opportunity.id,
                                     m.CompanySource.verified.is_(True), m.CompanySource.id != source.id).limit(1))
                can_promote = source.verified or not authority_other
                promoted_fields = set()
                if can_promote:
                    for key, value in values.items():
                        clearable = key in {"requirements", "skills", "risk_reasons"} and bool(values["description"])
                        if value is None or value == "" or (value == [] and not clearable) or value == {}:
                            continue
                        if key in {"work_mode", "country"} and str(value).lower() in {"unknown", "unclear", "not specified"}:
                            continue
                        if key == "compensation" and value.get("kind") == "unknown" and opportunity.compensation and opportunity.compensation.get("kind") != "unknown":
                            continue
                        if key == "trust_state" and value == "unassessed" and source.verified:
                            value = "official_source"
                        if key == "data":
                            value = {**(opportunity.data or {}), **{k:v for k,v in value.items() if v is not None}}
                        if key == "description" and value:
                            opportunity.data = {**(opportunity.data or {}), "description_checked_at": iso(now), "description_source_id": source.id}
                        setattr(opportunity, key, value)
                        promoted_fields.add(key)
                snapshot = m.Snapshot(job_source_id=appearance.id, fetch_run_id=run.id, content_hash=digest,
                                       raw=json_value(raw_job.get("raw") or raw_job), normalized=json_value(values))
                db.add(snapshot)
                db.flush()
                for field in ["title", "description", "location", "country", "work_mode", "compensation", "posted_at", "deadline", "requisition_id", "requirements", "skills", "canonical_url", "apply_url"]:
                    value = values.get(field)
                    if value is not None and value != "" and value != [] and value != {}:
                        db.add(m.Evidence(opportunity_id=opportunity.id, snapshot_id=snapshot.id, field=field, value=json_value(value),
                                          source_url=values["canonical_url"] or source.url,
                                          confidence="source_stated" if source.verified else "observed_unverified",
                                          method="derived_rules" if field == "requirements" and not raw_job.get("requirements") else "source_field",
                                          data={"company_source_id": source.id, "promoted": field in promoted_fields}))
                appearance.latest_hash = digest
                if values["description"]:
                    appearance.last_detail_checked = now
                _evaluate_and_store(db, opportunity, profile, facts=facts)
                if not created:
                    stats["updated"] += 1
                _audit(db, "opportunity.discovered" if created else "opportunity.changed",
                       ("Discovered: " if created else "Source update: ") + opportunity.title,
                       "opportunity", opportunity.id, data={"snapshot_id": snapshot.id, "source_id": source.id,
                         "changed_fields": [k for k, v in values.items() if old_values[k] != json_value(v)]})
            else:
                stats["unchanged"] += 1
            touched.add(opportunity.id)
        except (ValueError, TypeError, KeyError) as exc:
            stats["invalid"] += 1
            issues.append(str(exc)[:300])

    from .source_health import budget_only
    # A bounded detail pass does not invalidate a proven listing inventory.
    # Other budgets (pages/time/records) and every transport/schema error do.
    detail_only = inventory_complete is True and bool(error) and all(part.strip()=='detail_limit_reached' for part in str(error).split(';'))
    listing_proven = bool(complete if inventory_complete is None else inventory_complete)
    effective_complete = bool(listing_proven and (not error or detail_only) and not issues and coverage_scope == "full")
    if inventory_ids is not None:
        inventory_ids={str(x) for x in inventory_ids}
        if (set(existing)&inventory_ids)-seen:
            effective_complete=False;issues.append("Storage filter omitted an existing source appearance")
    if listing_proven and coverage_scope=="full" and observed_count is not None and int(observed_count) > (len(inventory_ids) if inventory_ids is not None else len(seen)):
        effective_complete = False
        issues.append("Reported inventory exceeds unique accepted records; completeness rejected")
    prior_count = len(existing) if inventory_ids is not None else source.job_count or 0
    config = dict(source.config or {})
    if coverage_scope!='targeted':config['board_checked_at']=now.isoformat()
    elif 'board_checked_at' not in config and source.last_checked:
        config['board_checked_at']=aware(source.last_checked).isoformat()
    anomalous = effective_complete and prior_count >= 1 and len(seen) < prior_count * 0.2
    if anomalous:
        fingerprint = stable_hash(sorted(seen))
        repeat = int(config.get("anomaly_repeats", 0)) + 1 if config.get("anomaly_fingerprint") == fingerprint else 1
        config.update(anomaly_fingerprint=fingerprint, anomaly_repeats=repeat)
        if repeat < 2:
            effective_complete = False
            issues.append("Abrupt inventory loss quarantined pending an independent repeated complete observation")
    elif effective_complete:
        config.pop("anomaly_fingerprint", None)
        config.pop("anomaly_repeats", None)
    source.config = config

    if effective_complete:
        grace = float(get_settings(db).get("closure_grace_hours", 48))
        for external_id, appearance in existing.items():
            if external_id in seen or appearance.status == 'historical_alias':
                continue
            appearance.missed_complete_runs = (appearance.missed_complete_runs or 0) + 1
            if appearance.first_missing_at is None:
                appearance.first_missing_at = now
            elapsed = now - aware(appearance.first_missing_at)
            previous = appearance.status
            if appearance.missed_complete_runs >= 2:
                appearance.status = "confirmed_closed" if elapsed >= timedelta(hours=grace) else "possibly_closed"
            if appearance.status != previous:
                stats["closed" if appearance.status == "confirmed_closed" else "possibly_closed"] += 1
                _audit(db, "source.availability_changed", f"Source availability: {appearance.opportunity.title}",
                       "opportunity", appearance.opportunity_id, data={"source_id": source.id, "status": appearance.status,
                       "missing_complete_runs": appearance.missed_complete_runs, "first_missing_at": iso(appearance.first_missing_at)})
            touched.add(appearance.opportunity_id)
        source.job_count = len(seen)
    db.flush()
    for opportunity_id in touched:
        op = db.get(m.Opportunity, opportunity_id)
        reconcile_availability(db,op)
    soft=budget_only(error)
    scoped_complete = listing_proven and not error and not issues and coverage_scope in {'query','discovery'}
    status = "error" if error and not soft else "quarantined" if issues else "partial" if soft else "complete" if effective_complete else "scoped_complete" if scoped_complete else "partial"
    prior_board=(source.config or {}).get('board_health') or {}
    prior_board_success=prior_board.get('last_success',iso(source.last_success))
    prior_board_failures=int(prior_board.get('consecutive_failures',source.consecutive_failures) or 0)
    source.last_checked = now
    source.status = status
    source.last_error = (str(error) if error else "; ".join(issues))[:4000] or None
    if (error and not soft) or issues:
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
    else:
        source.consecutive_failures = 0
        source.last_success = now
    if coverage_scope != 'targeted':
        source.config={**source.config,'board_health':{'status':status,'last_error':source.last_error,
            'last_success':prior_board_success if (error and not soft) or issues else iso(now),
            'consecutive_failures':prior_board_failures+1 if (error and not soft) or issues else 0,
            'full_inventory':effective_complete,'coverage_scope':coverage_scope,
            'inventory_complete':listing_proven and not issues and (inventory_complete is True or not error),
            'description_complete':collection_metadata['description_complete'] if collection_metadata and collection_metadata.get('description_complete') is not None else not error,
            'description_scope':collection_metadata.get('description_scope') if collection_metadata else None,
            'description_target_count':collection_metadata.get('description_target_count') if collection_metadata else None}}
    run.status, run.complete, run.finished_at = status, effective_complete, now
    run.error = source.last_error
    run.data = {**stats, "accepted_unique": len(seen), "requested_complete": bool(complete), "storage_filtered":inventory_ids is not None, "parsed_inventory_count":len(inventory_ids) if inventory_ids is not None else len(seen), "issues": issues,
                "can_infer_absence": effective_complete, "employer_source_verified": source.verified}
    if collection_metadata is not None:
        run.data['collection']=json_value(collection_metadata)
        if coverage_scope != 'targeted':
            checkpoints={target:collection_metadata[key] for key,target in [
                ('next_detail_cursor','detail_cursor'),('next_listing_cursor','listing_cursor'),
                ('next_retained_detail_cursor','retained_detail_cursor')]
                if collection_metadata.get(key) is not None}
            source.config={**source.config,**checkpoints}
    _audit(db, "source.fetched", f"{source.company.name}: {len(seen)} observations ({status})", "source", source.id,
           data={"run_id": run.id, **run.data})
    db.commit()
    return {"run_id": run.id, "source_id": source.id, "status": status, "complete": effective_complete,
            "coverage_scope": coverage_scope, "observed_count": run.observed_count, "accepted": len(seen),
            "opportunity_ids": sorted(touched), "error": run.error, **stats}


def _counter_rows(counter):
    return [{"name": str(name or "Unknown"), "count": count} for name, count in counter.most_common()]


def saved_refresh_candidates(db, *, older_than_hours=None, limit=20):
    """Bounded saved-detail refresh plan for the worker, grouped by board.

    IDs/URLs identify a targeted subset, never an inventory or closure partition.
    Disabled/manual-only sources remain excluded and failed boards honor backoff.
    """
    settings = get_settings(db)
    hours = float(older_than_hours if older_than_hours is not None else settings.get("saved_detail_refresh_hours", 24))
    now = utcnow()
    cutoff = now - timedelta(hours=max(1, hours))
    appearances = db.scalars(select(m.JobSource).join(m.Opportunity).join(m.CompanySource).where(
        m.Opportunity.saved.is_(True), m.Opportunity.status != "confirmed_closed", m.CompanySource.enabled.is_(True),
        or_(m.JobSource.last_detail_checked.is_(None), m.JobSource.last_detail_checked <= cutoff)
    ).order_by(m.CompanySource.verified.desc(), m.JobSource.last_detail_checked.asc().nullsfirst(), m.JobSource.id)).all()
    chosen, grouped = set(), {}
    for appearance in appearances:
        if len(chosen) >= max(1, min(int(limit), 50)):
            break
        if appearance.opportunity_id in chosen:
            continue
        source = appearance.company_source
        if source.consecutive_failures and source.last_checked:
            retry_hours = min(72, 2 ** min(source.consecutive_failures, 6))
            if now - aware(source.last_checked) < timedelta(hours=retry_hours):
                continue
        url = canonicalize_url(appearance.url or appearance.opportunity.canonical_url)
        if not url:
            continue
        if source.id not in grouped:
            data = row_dict(source)
            data.update(company_name=source.company.name, company_domain=source.company.domain,
                        config={**(source.config or {}), "refresh_external_ids": [], "refresh_jobs": []}, target_opportunity_ids=[])
            grouped[source.id] = data
        op = appearance.opportunity
        grouped[source.id]["config"]["refresh_external_ids"].append(appearance.external_id)
        grouped[source.id]["config"]["refresh_jobs"].append({"external_id": appearance.external_id,
            "requisition_id": appearance.requisition_id, "canonical_url": url, "apply_url": op.apply_url,
            "opportunity_id": op.id, "title": op.title, "company_name": op.company.name, "company_domain": op.company.domain})
        grouped[source.id]["target_opportunity_ids"].append(op.id)
        chosen.add(op.id)
    return list(grouped.values())


def _histogram(values):
    bins = Counter({"0â€“19": 0, "20â€“39": 0, "40â€“59": 0, "60â€“79": 0, "80â€“100": 0, "Unknown": 0})
    for score in values:
        key = "Unknown" if score is None else ["0â€“19", "20â€“39", "40â€“59", "60â€“79", "80â€“100"][min(4, max(0, int(score) // 20))]
        bins[key] += 1
    return [{"range": key, "count": value} for key, value in bins.items()]


def _is_relevant(op):
    return op.role_family in {"SWE", "Data", "AI_ML", "Adjacent"} and op.opportunity_type in {"internship", "possible_internship", "apprenticeship"}

def _in_primary_market(op):
    import re
    return (op.country or '').lower() in {'in','ind','india'} or bool(re.search(r'\b(india|bengaluru|bangalore|chennai|hyderabad|mumbai|pune|delhi|noida|gurugram|gurgaon|kolkata|coimbatore|kochi|thiruvananthapuram|mysuru|mangaluru|trivandrum|chandigarh|jaipur|indore|ahmedabad|remote india)\b',op.location or '',re.I))


def analytics(db, days=30, scope='all'):
    if scope not in {'india','all'}:
        raise ValueError('Analytics scope must be india or all')
    days = max(1, min(730, int(days)))
    now, settings = utcnow(), get_settings(db)
    since = now - timedelta(days=days)
    # Canonical objects are counted once; source relationships are separate measures.
    opportunities = db.scalars(select(m.Opportunity).options(joinedload(m.Opportunity.company),selectinload(m.Opportunity.sources).joinedload(m.JobSource.company_source))).all()
    raw_count = len(opportunities)
    from .shortlist import exclusions, hidden
    rules = exclusions(db)
    opportunities = [o for o in opportunities if not hidden(o, rules)]
    if scope == 'india':
        from .search_policy import TITLE_EXCLUSIONS
        opportunities = [o for o in opportunities if (not settings.get('personal_location_policy') or _personal_scope(o)) and _in_primary_market(o) and o.role_family in (settings.get('roles') or ['SWE','Data','AI_ML','Adjacent']) and o.opportunity_type in {'internship','possible_internship'} and (not settings.get('personal_target_filter') or not re.search(TITLE_EXCLUSIONS,o.title,re.I))]
    scoped_ids = {o.id for o in opportunities}
    mirror_to_canonical = {id: o.id for o in opportunities for id in (o.data or {}).get("mirror_ids", [])}
    recent = [o for o in opportunities if aware(o.first_seen) >= since]
    applications = db.scalars(select(m.Application)).all()
    recent_apps = [a for a in applications if a.submitted_at and aware(a.submitted_at) >= since]
    runs = db.scalars(select(m.FetchRun).where(m.FetchRun.created_at >= since)).all()
    sources = db.scalars(select(m.CompanySource).options(joinedload(m.CompanySource.company))).all()
    relationships = [r for r in db.scalars(select(m.JobSource)).all() if r.opportunity_id in scoped_ids or r.opportunity_id in mirror_to_canonical]
    per_source = {}
    for appearance in relationships:
        per_source.setdefault(appearance.company_source_id, set()).add(mirror_to_canonical.get(appearance.opportunity_id, appearance.opportunity_id))
    membership = {}
    for appearance in relationships:
        membership.setdefault(mirror_to_canonical.get(appearance.opportunity_id, appearance.opportunity_id), set()).add(appearance.company_source_id)
    discovered = Counter(aware(o.first_seen).date().isoformat() for o in recent)
    daily = [{"date": (now.date() - timedelta(days=i)).isoformat(), "count": discovered[(now.date() - timedelta(days=i)).isoformat()]} for i in range(days - 1, -1, -1)]
    weeks = Counter((aware(a.submitted_at).date() - timedelta(days=aware(a.submitted_at).weekday())).isoformat() for a in recent_apps)
    stage_counts = Counter(a.stage for a in applications)
    funnel = [{"stage": stage, "count": stage_counts[stage]} for stage in ["ready", "applied", "oa", "interview", "offer", "rejected", "withdrawn"]]
    skills = Counter()
    for opportunity in recent:
        skills.update(set(str(s.get("name", "")) if isinstance(s, dict) else str(s) for s in (opportunity.skills or [])))
    source_rows = []
    for source in sources:
        source_runs = [r for r in runs if r.company_source_id == source.id]
        ids = per_source.get(source.id, set())
        source_rows.append({"id": source.id, "name": source.company.name, "provider": source.provider,
                            "count": len(ids), "unique_jobs": len(ids), "observed_exclusive": sum(len(membership[x]) == 1 for x in ids),
                            "complete_runs": sum(r.complete for r in source_runs), "runs": len(source_runs),
                            "failures": sum(r.status in {"error", "quarantined"} for r in source_runs),
                            "status": source.status, "last_success": iso(source.last_success)})
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = db.scalars(select(m.AIUsage).where(m.AIUsage.created_at >= month_start)).all()
    spent = round(sum(x.cost_usd or 0 for x in usage), 6)
    reserved = round(sum(x.reserved_usd or 0 for x in usage if x.status == "reserved"), 6)
    budget = float(settings.get("ai_monthly_budget_usd", 2.5))
    pay = []
    for opportunity in recent:
        c = opportunity.compensation or {}
        if c.get("min") is not None or c.get("max") is not None:
            pay.append({"opportunity_id": opportunity.id, "company": opportunity.company.name,
                        "kind": c.get("kind", "unknown"), "currency": c.get("currency"), "period": c.get("period"),
                        "min": c.get("min"), "max": c.get("max"), "label": c.get("label")})
    resume_counts = {}
    for app in applications:
        if not app.resume_version_id:
            continue
        bucket = resume_counts.setdefault(app.resume_version_id, {"resume_version_id": app.resume_version_id, "applications": 0, "interviews": 0, "offers": 0})
        bucket["applications"] += 1
        bucket["interviews"] += app.stage in {"interview", "offer"}
        bucket["offers"] += app.stage == "offer"
    n = len(recent)
    known = lambda field: sum(bool(getattr(o, field)) for o in recent)
    return {"scope": scope, "summary": {"raw_collected_records": raw_count, "opportunities": len(opportunities), "new_opportunities": n, "relevant_opportunities": sum(_is_relevant(o) for o in recent),
                         "saved": sum(o.saved for o in opportunities), "applications": len(applications), "submitted_in_period": len(recent_apps),
                         "companies": db.scalar(select(func.count()).select_from(m.Company).where(m.Company.metadata_json["source_holder"].as_boolean().is_not(True))) or 0,
                         "source_appearances": len(relationships), "canonical_opportunities": len(opportunities),
                         "duplicates_associated": max(0, len(relationships) - len(opportunities)),
                         "description_coverage": known("description") / n if n else None,
                         "location_coverage": known("location") / n if n else None,
                         "posted_date_coverage": known("posted_at") / n if n else None},
            "daily_discoveries": daily, "applications_by_week": [{"week": w, "count": c} for w, c in sorted(weeks.items())],
            "funnel": funnel, "sources": source_rows, "roles": _counter_rows(Counter(o.role_family for o in recent)),
            "locations": _counter_rows(Counter(o.location or "Unknown" for o in recent)), "skills": _counter_rows(skills)[:40],
            "fit_distribution": _histogram(o.fit_score for o in recent), "worth_distribution": _histogram(o.worth_score for o in recent),
            "compensation": pay, "resume_outcomes": list(resume_counts.values()),
            "health": {"complete_runs": sum(r.complete for r in runs), "total_runs": len(runs),
                       "failures": sum(r.status in {"error", "quarantined"} for r in runs),
                       "success_rate": sum(r.complete for r in runs) / len(runs) if runs else None,
                       "healthy_sources": sum(s.status == "complete" for s in sources), "sources": len(sources)},
            "ai_usage": {"spent": spent, "reserved": reserved, "budget": budget, "remaining": max(0, round(budget - spent - reserved, 6))},
            "definitions": {"scope": "Visible India technical internships and possible internships; profile eligibility is not implied." if scope == 'india' else "Visible global canonical roles, including full-time and nontechnical roles. Raw collected records also include retained excluded roles and mirrors.", "exclusions": "Owner-excluded roles and companies are omitted from opportunity metrics. Proven mirrors count once while their source appearances remain visible. Historical application metrics are retained.", "collection_health": "Worker and source health cover all monitored sources regardless of the selected opportunity scope.", "period": f"Last {days} days", "discovery": "First observation of a canonical opportunity; not the employer posting date.",
                            "funnel": "Current application stage counts, not cohort conversion rates.",
                            "source_unique": "Distinct canonical opportunities seen by each monitored source; source counts can overlap.",
                            "exclusivity": "Observed only in one monitored source appearance; no claim of global exclusivity.",
                            "resume_outcomes": "Descriptive associations; small samples and selection differences prevent causal conclusions.",
                            "compensation": "Keep currency and period separate; unknown pay is not zero.",
                            "missingness": "Zero-denominator quality rates are null; unassessed scores remain Unknown."}}


def dashboard(db):
    now = utcnow()
    settings=get_settings(db)
    from .search_policy import TITLE_EXCLUSIONS
    opportunities = db.scalars(select(m.Opportunity).options(joinedload(m.Opportunity.company),selectinload(m.Opportunity.sources).joinedload(m.JobSource.company_source))).all()
    applications = db.scalars(select(m.Application)).all()
    from .shortlist import assessment, exclusions, hidden, appearances_for
    rules = exclusions(db)
    opportunities = [o for o in opportunities if not hidden(o, rules)]
    sources = db.scalars(select(m.CompanySource).options(joinedload(m.CompanySource.company))).all()
    relevant = [o for o in opportunities if (not settings.get('personal_location_policy') or _personal_scope(o)) and _is_relevant(o) and _in_primary_market(o) and o.status == "active" and o.role_family in (settings.get('roles') or ['SWE','Data','AI_ML','Adjacent']) and (not settings.get('personal_target_filter') or not re.search(TITLE_EXCLUSIONS,o.title,re.I)) and assessment(o, appearances_for(db, o) if (o.data or {}).get("mirror_ids") else o.sources, rules, now=now)["recommended"]]
    from .company_priority import priority
    relevant.sort(key=lambda o: (priority(o.company)["score"], o.fit_score if o.fit_score is not None else -1, aware(o.first_seen)), reverse=True)
    deadline_rows = [task_dict(t) for t in db.scalars(select(m.Task).where(m.Task.completed.is_(False), m.Task.due_at.is_not(None)).order_by(m.Task.due_at).limit(10)).all()]
    due_ids = {x.get("opportunity_id") for x in deadline_rows}
    for opportunity in sorted((o for o in relevant if o.deadline and aware(o.deadline) >= now and o.id not in due_ids), key=lambda o: aware(o.deadline))[:10]:
        deadline_rows.append({"id": "opportunity:" + opportunity.id, "title": opportunity.title,
                              "opportunity_id": opportunity.id, "due_at": iso(opportunity.deadline),
                              "date_precision": (opportunity.data or {}).get("deadline_precision", "unknown"), "kind": "application_deadline", "completed": False})
    deadline_rows.sort(key=lambda x: x.get("due_at") or "9999")
    history = Counter(aware(o.first_seen).date().isoformat() for o in relevant)
    return {"stats": {"new_opportunities": sum(aware(o.first_seen) >= now - timedelta(days=1) for o in relevant),
                      "saved": sum(o.saved for o in opportunities), "applications": len(applications),
                      "active_applications": sum(a.stage not in {"rejected", "withdrawn"} for a in applications),
                      "interviews": sum(a.stage == "interview" for a in applications),
                      "companies": db.scalar(select(func.count()).select_from(m.Company).where(m.Company.metadata_json["source_holder"].as_boolean().is_not(True))) or 0,
                      "sources_healthy": sum(s.status == "complete" for s in sources)},
            "top_opportunities": [opportunity_dict(db, o, detail=False, rules=rules) for o in relevant[:8]], "deadlines": deadline_rows[:10],
            "recent_activity": [activity_dict(x) for x in db.scalars(select(m.Activity).order_by(m.Activity.created_at.desc()).limit(15)).all()],
            "funnel": [{"stage": stage, "count": sum(a.stage == stage for a in applications)} for stage in ["ready", "applied", "oa", "interview", "offer", "rejected"]],
            "source_health": [source_dict(s) for s in sorted(sources, key=lambda s: (s.status == "complete", s.company.name))[:12]],
            "notifications": [row_dict(n) for n in db.scalars(select(m.Notification).where(m.Notification.read.is_(False)).order_by(m.Notification.created_at.desc()).limit(10)).all()],
            "daily_discoveries": [{"date": (now.date() - timedelta(days=i)).isoformat(), "count": history[(now.date() - timedelta(days=i)).isoformat()]} for i in range(13, -1, -1)]}


def _personal_scope(op):
    from .search_policy import location_decision,PHD_ONLY
    return location_decision(op.location,op.country,op.work_mode)=='allowed' and not re.search(PHD_ONLY,op.title,re.I) and op.eligibility!='probably ineligible'


def repair_workday_identity(db, appearance_id, *, apply=False):
    """Correct a legacy ID only from its own primary native snapshot; keep clocks."""
    from urllib.parse import urlsplit
    from .ingestion.adapters import workday_listing_identifiers
    appearance = _require(db, m.JobSource, appearance_id)
    source, op = appearance.company_source, appearance.opportunity
    result = {'appearance_id': appearance.id, 'opportunity_id': op.id, 'applied': False}
    if source.provider.lower() != 'workday' or source.company_id != op.company_id:
        return {**result, 'reason': 'Matching Workday employer association required.'}
    snap = db.scalar(select(m.Snapshot).where(m.Snapshot.job_source_id == appearance.id).order_by(m.Snapshot.created_at.desc(), m.Snapshot.id.desc()).limit(1))
    raw = (snap.raw or {}) if snap else {}
    raw = raw.get('source_payload', raw)
    detail = raw.get('detail') or {}
    detail = detail.get('jobPostingInfo', detail)
    listing = raw.get('listing') or {}
    native = urlsplit(str(detail.get('externalUrl') or ''))
    recorded = urlsplit(str(appearance.url or ''))
    board = urlsplit(source.url)
    if not re.search(r'\.myworkday(?:jobs|site)\.com$', board.hostname or ''):
        return {**result, 'reason': 'Native Workday host required.'}
    path = listing.get('externalPath') or ('/job/' + native.path.split('/job/', 1)[1] if '/job/' in native.path else '')
    req = str(detail.get('jobReqId') or '')
    posting = str(detail.get('jobPostingId') or '')
    if (not snap or not req or not posting or not path or native.hostname != board.hostname
        or recorded.hostname != board.hostname or native.path.casefold() != recorded.path.casefold()
        or path.rsplit('/',1)[-1] != posting or str(detail.get('title') or '').strip().casefold() != op.title.strip().casefold()
        or (listing.get('title') and str(listing['title']).strip().casefold() != op.title.strip().casefold())
        or (appearance.requisition_id and appearance.requisition_id != req)):
        return {**result, 'reason': 'Primary native title, path, explicit requisition or employer does not agree.'}
    expected, expected_req = workday_listing_identifiers({'externalPath':path,'bulletFields':[req]})
    if not expected_req:
        return {**result, 'reason':'Explicit requisition does not agree with the posting path.'}
    collision = db.scalar(select(m.JobSource).where(m.JobSource.company_source_id == source.id, m.JobSource.external_id == expected, m.JobSource.id != appearance.id))
    if collision and (collision.opportunity_id != op.id or canonicalize_url(collision.url) != canonicalize_url(appearance.url)):
        return {**result,'reason':'Native identity belongs to a different appearance; manual review required.'}
    before = {'external_id':appearance.external_id,'requisition_id':appearance.requisition_id,'status':appearance.status}
    evidence = {'snapshot_id':snap.id,'native_path':path,'jobReqId':req,'jobPostingId':posting,'native_url':detail['externalUrl'],
                'before':before,'historical_evidence_only':True,'clocks_unchanged':True,'source_verification_unchanged':True,'canonical_appearance_id':collision.id if collision else appearance.id}
    if apply:
        if collision:
            appearance.status = 'historical_alias'
        else:
            appearance.external_id, appearance.requisition_id = expected, req
        db.add(m.IdentityDecision(opportunity_id=op.id,job_source_id=appearance.id,
                                 decision='source_identity_alias' if collision else 'source_identity_repaired',evidence=evidence))
        db.flush()
    return {**result,'applied':apply,'expected_id':expected,'requisition_id':req,'alias':bool(collision),'evidence':evidence}


def reconcile_shortlist_quality(db, *, apply=False, opportunity_ids=None, limit=None, offset=0):
    """Dry-run first. Never deletes rows, moves foreign keys or resets clocks.

    Mirrors become reversible visibility aliases. Existing application/resume
    references remain on their original opportunity; provenance is presented on
    the canonical role. Only exact employer/URL or trusted requisition matches
    qualify; ambiguous historical Workday IDs are reported for review.
    """
    from .shortlist import employer_identity, proven_mirror, trusted_requisition
    options = (joinedload(m.Opportunity.company), selectinload(m.Opportunity.sources).joinedload(m.JobSource.company_source))
    target_stmt = select(m.Opportunity).options(*options).order_by(m.Opportunity.first_seen, m.Opportunity.id)
    if opportunity_ids is not None: target_stmt = target_stmt.where(m.Opportunity.id.in_(list(opportunity_ids)))
    if limit is not None: target_stmt = target_stmt.offset(max(0, int(offset))).limit(max(1, min(1000, int(limit))))
    targets = db.scalars(target_stmt).all()
    target_ids = {op.id for op in targets}
    if opportunity_ids is not None or limit is not None:
        # Include the entire same-employer/title candidate group when evaluating
        # a bounded page, so a canonical role outside that page is not missed.
        keys = {(op.company_id, op.title.strip().lower()) for op in targets}
        ops = db.scalars(select(m.Opportunity).where(tuple_(m.Opportunity.company_id, func.lower(func.trim(m.Opportunity.title))).in_(list(keys))).options(*options).order_by(m.Opportunity.first_seen, m.Opportunity.id)).all() if keys else []
    else: ops = targets
    op_ids = [op.id for op in ops]
    appearance_ids = [src.id for op in ops for src in op.sources]
    ranked = select(m.Snapshot.id, func.row_number().over(partition_by=m.Snapshot.job_source_id, order_by=(m.Snapshot.created_at.desc(), m.Snapshot.id.desc())).label("rn")).where(m.Snapshot.job_source_id.in_(appearance_ids)).subquery()
    snapshots = {snap.job_source_id:snap for snap in db.scalars(select(m.Snapshot).join(ranked, m.Snapshot.id == ranked.c.id).where(ranked.c.rn == 1))}
    evidence_by_field = {}
    for evidence in db.scalars(select(m.Evidence).where(m.Evidence.opportunity_id.in_(op_ids), m.Evidence.field.in_(["description", "requirements"])).order_by(m.Evidence.created_at.desc(), m.Evidence.id.desc())):
        if (evidence.data or {}).get("promoted"):
            evidence_by_field.setdefault((evidence.opportunity_id, evidence.field), evidence)
    evidence_snapshots = {snap.id:snap for snap in snapshots.values()}
    extra_ids = {e.snapshot_id for e in evidence_by_field.values() if e.snapshot_id} - set(evidence_snapshots)
    if extra_ids:
        evidence_snapshots.update({snap.id:snap for snap in db.scalars(select(m.Snapshot).where(m.Snapshot.id.in_(list(extra_ids))))})
    appearances = {src.id:src for op in ops for src in op.sources}
    profile = _latest_profile(db)
    evaluation_cache = {id:[] for id in target_ids}
    if apply:
        for evaluation in db.scalars(select(m.Evaluation).where(m.Evaluation.opportunity_id.in_(list(target_ids))).order_by(m.Evaluation.created_at.desc(), m.Evaluation.id.desc())):
            evaluation_cache[evaluation.opportunity_id].append(evaluation)
    report = {"dry_run": not apply, "target_count": len(targets), "related_candidates": len(ops)-len(targets), "evaluation_candidates": len(targets), "evaluated": 0, "description_clocks_recovered": 0, "identity_review": [], "mirror_groups": [], "aliases_added": 0}
    buckets, group_requisitions = {}, {}
    reviewed_pairs = {frozenset((d.opportunity_id, d.candidate_id)) for d in db.scalars(select(m.IdentityDecision).where(m.IdentityDecision.decision == "confirmed_mirror", m.IdentityDecision.reversed_at.is_not(None))) if d.candidate_id}
    for op in ops:
        data = dict(op.data or {})
        historical = []
        for src in op.sources:
            if src.status == 'historical_alias': continue
            if src.company_source.provider.lower() != "workday": continue
            from .ingestion.adapters import workday_listing_identifiers
            snap = snapshots.get(src.id)
            raw = (snap.raw or {}) if snap else {}
            # Collector snapshots wrap provider data and separate the primary
            # listing from detail recommendations. Follow only these declared
            # wrappers; do not search arbitrary nested similar-job records.
            if isinstance(raw, dict): raw = raw.get("source_payload", raw)
            if isinstance(raw, dict): raw = raw.get("listing", raw)
            if isinstance(raw, dict) and raw.get("externalPath"):
                expected_id, expected_req = workday_listing_identifiers(raw)
                if src.external_id != expected_id or (src.requisition_id and src.requisition_id != expected_req):
                    historical.append({"source_id": src.company_source_id, "appearance_id": src.id, "external_id": src.external_id,
                                       "observed_path": raw.get("externalPath"), "expected_id": expected_id, "reason": "Historic Workday ID does not match the observed posting path."})
        if historical:
            report["identity_review"].append({"opportunity_id": op.id, "observations": historical})
            if apply and op.id in target_ids: data["identity_review"] = {"reason": "Historic Workday source identity needs review", "observations": historical}
        if op.description and not data.get("description_checked_at"):
            evidence = evidence_by_field.get((op.id, "description"))
            if evidence and evidence.value == op.description and (evidence.data or {}).get("promoted") and evidence.snapshot_id:
                snapshot = evidence_snapshots.get(evidence.snapshot_id)
                appearance = appearances.get(snapshot.job_source_id) if snapshot else None
                if snapshot and appearance:
                    report["description_clocks_recovered"] += int(op.id in target_ids)
                    if apply and op.id in target_ids:
                        # Recover the actual historical observation, never now.
                        data.update(description_checked_at=iso(snapshot.created_at), description_source_id=appearance.company_source_id)
        if apply and op.id in target_ids:
            op.data = data
            latest_requirements = evidence_by_field.get((op.id, "requirements"))
            if op.description and (not latest_requirements or latest_requirements.method == "derived_rules"):
                op.requirements = classify(op.description, op.title)["requirements"]
            _evaluate_and_store(db, op, profile, evaluations=evaluation_cache[op.id])
            report["evaluated"] += 1
        if historical or data.get("duplicate_of"): continue
        values = row_dict(op)
        name = employer_identity(values, op.company.name)
        trusted = trusted_requisition(db, op, snapshots)
        keys = []
        if op.canonical_url: keys.append((op.company_id, name, "url", canonicalize_url(op.canonical_url)))
        if op.requisition_id and trusted: keys.append((op.company_id, name, "req", op.requisition_id.casefold()))
        candidates = {c.id: c for k in keys for c in buckets.get(k, [])}
        for candidate in candidates.values():
            if candidate.id not in target_ids and op.id not in target_ids: continue
            if frozenset((candidate.id, op.id)) in reviewed_pairs: continue
            if (candidate.data or {}).get("identity_review"): continue
            candidate_trusted = trusted_requisition(db, candidate, snapshots)
            reason = proven_mirror(row_dict(candidate), values, employer_a=employer_identity({"data": candidate.data}, candidate.company.name), employer_b=name,
                                   trusted_a=candidate_trusted, trusted_b=trusted)
            if reason == "exact_requisition" and {x.company_source_id for x in candidate.sources} & {x.company_source_id for x in op.sources}:
                continue
            if not reason: continue
            reqs = group_requisitions.get(candidate.id, {str(candidate.requisition_id).casefold()} if candidate.requisition_id else set())
            if op.requisition_id and reqs and op.requisition_id.casefold() not in reqs: continue
            if op.requisition_id: group_requisitions[candidate.id] = reqs | {op.requisition_id.casefold()}
            report["mirror_groups"].append({"canonical_id": candidate.id, "mirror_id": op.id, "reason": reason,
                                            "company_id": op.company_id, "requisition_id": op.requisition_id, "canonical_url": op.canonical_url})
            if apply:
                candidate.data = {**(candidate.data or {}), "mirror_ids": list(dict.fromkeys([*(candidate.data or {}).get("mirror_ids", []), op.id]))}
                op.data = {**(op.data or {}), "duplicate_of": candidate.id}
                db.add(m.IdentityDecision(opportunity_id=candidate.id, candidate_id=op.id, decision="confirmed_mirror", evidence={"reason": reason, "reversible_visibility_alias": True, "history_retained": True}))
            report["aliases_added"] += 1
            break
        else:
            for key in keys: buckets.setdefault(key, []).append(op)
    if apply:
        _audit(db, "shortlist.reconciled", "Shortlist quality reconciled", data={k: v for k, v in report.items() if k not in {"identity_review", "mirror_groups"}})
        db.flush()
    return report


def reverse_shortlist_alias(db, mirror_id):
    """Restore a reviewed mirror without deleting its decision or history."""
    mirror = _require(db, m.Opportunity, mirror_id)
    canonical_id = (mirror.data or {}).get("duplicate_of")
    if not canonical_id: return {"restored": False, "opportunity_id": mirror_id}
    canonical = _require(db, m.Opportunity, canonical_id)
    mirror.data = {k:v for k,v in (mirror.data or {}).items() if k != "duplicate_of"}
    canonical.data = {**(canonical.data or {}), "mirror_ids": [x for x in (canonical.data or {}).get("mirror_ids", []) if x != mirror_id]}
    for decision in db.scalars(select(m.IdentityDecision).where(m.IdentityDecision.opportunity_id == canonical_id, m.IdentityDecision.candidate_id == mirror_id, m.IdentityDecision.decision == "confirmed_mirror", m.IdentityDecision.reversed_at.is_(None))):
        decision.reversed_at = utcnow()
    _audit(db, "shortlist.alias_reversed", "Restored a reviewed related listing", "opportunity", mirror_id, data={"canonical_id": canonical_id, "history_retained": True})
    db.flush()
    return {"restored": True, "opportunity_id": mirror_id, "canonical_id": canonical_id}
