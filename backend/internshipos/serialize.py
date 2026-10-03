"""JSON contracts shared by API and local worker; secrets never serialized here."""
from datetime import date, datetime

from sqlalchemy import inspect, or_, select

from .db import aware
from . import models as m


def iso(value):
    return aware(value).isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value.isoformat() if isinstance(value, date) else value


def json_value(value):
    if isinstance(value, (datetime, date)):
        return iso(value)
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def row_dict(obj):
    if obj is None:
        return None
    return {c.key: json_value(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs
            if c.key not in {"credentials_encrypted", "contents"}}


def source_dict(obj):
    result = row_dict(obj)
    result["company"] = {"id": obj.company.id, "name": obj.company.name, "domain": obj.company.domain, "verified": obj.company.verified}
    from .source_health import health
    result["health"]=json_value(health(obj))
    result["company_name"] = obj.company.name
    result["board_url"] = obj.url
    return result


def activity_dict(obj):
    result = row_dict(obj)
    result["can_undo"] = obj.before is not None and obj.undone_at is None and obj.entity_type in {"opportunity", "application", "task", "settings", "profile"}
    return result


def task_dict(obj):
    return row_dict(obj)


def opportunity_dict(db, obj, detail=True):
    if obj is None:
        return None
    result = row_dict(obj)
    result["company"] = {"id": obj.company.id, "name": obj.company.name, "domain": obj.company.domain,
                         "verified": obj.company.verified, "logo_url": obj.company.logo_url}
    from .company_priority import priority
    from .search_policy import location_decision
    result["company_priority"]=priority(obj.company)
    result["location_decision"]=location_decision(obj.location,obj.country,obj.work_mode)
    result["compensation"] = {"kind": "unknown", "label": "Not stated", "min": None, "max": None,
                              "currency": None, "period": None, **(obj.compensation or {})}
    appearances = db.scalars(select(m.JobSource).where(m.JobSource.opportunity_id == obj.id)).all() if detail else obj.sources
    if obj.trust_state=='high_risk' or any('requests cryptocurrency payment' in str(r).lower() for r in (obj.risk_reasons or [])):
        result['trust_state']='high_risk'
    elif obj.risk_reasons or not obj.company.verified:
        result['trust_state']='needs_review'
    elif any(src.company_source.verified for src in appearances):
        result['trust_state']='verified'
    else:result['trust_state']='no_obvious_concern'
    result["sources"] = [{"id": src.id, "provider": src.company_source.provider,
                           "company_source_id": src.company_source_id, "external_id": src.external_id,
                           "requisition_id": src.requisition_id, "url": src.url,
                           "verified": src.company_source.verified, "status": src.status,
                           "first_seen": iso(src.first_seen), "last_seen": iso(src.last_seen)} for src in appearances]
    if not detail:
        for key in ('description','description_html','data'):result.pop(key,None)
        return result
    evaluation = db.scalar(select(m.Evaluation).where(m.Evaluation.opportunity_id == obj.id).order_by(m.Evaluation.created_at.desc()).limit(1))
    result["evaluation"] = evaluation.data if evaluation else {"fit_dimensions": [], "worth_dimensions": [], "unknowns": ["Not evaluated yet"], "evidence": []}
    application = db.scalar(select(m.Application).where(m.Application.opportunity_id == obj.id).order_by(m.Application.created_at.desc()).limit(1))
    result["application_id"] = application.id if application else None
    decisions = db.scalars(select(m.IdentityDecision).where(
        or_(m.IdentityDecision.opportunity_id == obj.id, m.IdentityDecision.candidate_id == obj.id),
        m.IdentityDecision.decision.in_(["probable", "possible"]), m.IdentityDecision.reversed_at.is_(None))).all()
    result["possible_duplicates"] = [{"id": d.id, "opportunity_id": d.candidate_id if d.opportunity_id == obj.id else d.opportunity_id,
                                       "decision": d.decision, "evidence": d.evidence} for d in decisions]
    evidence = db.scalars(select(m.Evidence).where(m.Evidence.opportunity_id == obj.id).order_by(m.Evidence.created_at.desc()).limit(80)).all()
    result["field_evidence"] = [row_dict(e) for e in evidence]
    return result


def application_dict(db, obj):
    if obj is None:
        return None
    result = row_dict(obj)
    result["opportunity"] = opportunity_dict(db, obj.opportunity)
    result["events"] = [row_dict(e) for e in db.scalars(select(m.ApplicationEvent).where(m.ApplicationEvent.application_id == obj.id).order_by(m.ApplicationEvent.created_at)).all()]
    return result
