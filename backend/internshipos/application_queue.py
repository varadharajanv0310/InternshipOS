"""Approved packs and single-use browser leases. This module never submits a form."""
import secrets
from datetime import timedelta
from sqlalchemy import select,func,text
from . import models as m
from .db import utcnow,aware
from .domain import stable_hash,canonicalize_url
from .search_policy import location_decision,PHD_ONLY
import re

def fingerprint(db,app):
    from .service import get_profile
    op=app.opportunity
    return stable_hash({'job':op.id,'title':op.title,'url':op.apply_url or op.canonical_url,'requirements':op.requirements,'description':op.description,'resume':app.resume_version_id,'profile':get_profile(db).get('id')})

def blockers(db,app,eligibility_reviewed=False):
    op=app.opportunity;reasons=[]
    from .shortlist import assessment, exclusions, appearances_for
    reasons.extend(assessment(op, appearances_for(db, op), exclusions(db))["review_reasons"])
    if app.stage!='ready':reasons.append('Application is not in Ready.')
    if op.status!='active':reasons.append('Job is not confirmed active.')
    if op.deadline and aware(op.deadline)<utcnow():reasons.append('Application deadline has passed.')
    if location_decision(op.location,op.country,op.work_mode)!='allowed':reasons.append('Location does not meet your policy.')
    if re.search(PHD_ONLY,op.title,re.I) or op.eligibility=='probably ineligible':reasons.append('Known eligibility conflict.')
    elif op.eligibility!='probably eligible' and not eligibility_reviewed:reasons.append('Review eligibility explicitly before approval.')
    if not op.company.verified or op.risk_reasons:reasons.append('Employer identity/risk needs review.')
    providers={s.company_source.provider for s in op.sources if s.company_source.verified}
    from .service import get_settings
    policy=get_settings(db).get('auto_apply',{})
    if not providers.intersection(policy.get('providers',[])):reasons.append('No verified, authorized submission provider.')
    version=db.get(m.ResumeVersion,app.resume_version_id) if app.resume_version_id else None
    if not version or version.status!='approved':reasons.append('Select an approved resume version.')
    url=canonicalize_url(op.apply_url or op.canonical_url or '')
    for other in db.scalars(select(m.Application).where(m.Application.id!=app.id)).all():
        if (other.opportunity_id==op.id or canonicalize_url(other.opportunity.apply_url or other.opportunity.canonical_url or '')==url) and (other.stage!='ready' or other.data.get('auto_apply',{}).get('state') in {'approved','in_progress','uncertain','submitted'}):
            reasons.append('A matching application is already submitted or queued.');break
    return list(dict.fromkeys(reasons))

def listing(db):
    rows=[]
    for app in db.scalars(select(m.Application).order_by(m.Application.created_at)).all():
        approval=(app.data or {}).get('auto_apply',{})
        current_blockers=blockers(db,app,approval.get('eligibility_reviewed',False))
        rows.append({'id':app.id,'company':app.opportunity.company.name,'title':app.opportunity.title,'url':app.opportunity.apply_url or app.opportunity.canonical_url,'state':approval.get('state','needs_review'),'stage':app.stage,'blockers':current_blockers,'approval_current':approval.get('fingerprint')==fingerprint(db,app) and not current_blockers})
    return {'items':rows,'total':len(rows),'execution':'User browser extension; no hosted browser worker.'}

def approve(db,id,eligibility_reviewed=False):
    app=db.get(m.Application,id)
    if not app:raise ValueError('Application not found.')
    prior=(app.data or {}).get('auto_apply',{})
    if prior.get('state') in {'in_progress','uncertain','submitted'}:raise ValueError('Resolve the previous submission before approving again.')
    reasons=blockers(db,app,eligibility_reviewed)
    if reasons:raise ValueError('; '.join(reasons))
    app.data={**app.data,'auto_apply':{'state':'approved','fingerprint':fingerprint(db,app),'resume_version_id':app.resume_version_id,'eligibility_reviewed':eligibility_reviewed,'approved_at':utcnow().isoformat()}}
    db.add(m.Activity(kind='application_approved',title='Application pack approved',entity_type='application',entity_id=id,data=app.data['auto_apply']));db.commit()
    return {'state':'approved','application_id':id}

def claim(db,id):
    # Serialize the global daily limit as well as each application lease.
    if db.bind.dialect.name=='postgresql':db.execute(text('SELECT pg_advisory_xact_lock(73104621)'))
    app=db.scalar(select(m.Application).where(m.Application.id==id).with_for_update())
    if not app:raise ValueError('Application not found.')
    from .service import get_settings
    policy=get_settings(db).get('auto_apply',{})
    if not policy.get('enabled'):raise ValueError('Automatic submission is disabled.')
    approval=(app.data or {}).get('auto_apply',{})
    if approval.get('state')!='approved':raise ValueError('This pack is not approved or already has a submission attempt.')
    if approval.get('fingerprint')!=fingerprint(db,app):raise ValueError('The job, profile or resume changed. Review the pack again.')
    reasons=blockers(db,app,approval.get('eligibility_reviewed',False))
    if reasons:raise ValueError('; '.join(reasons))
    start=utcnow().replace(hour=0,minute=0,second=0,microsecond=0)
    count=db.scalar(select(func.count()).select_from(m.Activity).where(m.Activity.kind=='submission_reserved',m.Activity.created_at>=start)) or 0
    if count>=policy.get('daily_limit',5):raise ValueError('Daily submission-attempt limit reached.')
    lease=secrets.token_urlsafe(32)
    app.data={**app.data,'auto_apply':{**approval,'state':'in_progress','lease':lease,'expires_at':(utcnow()+timedelta(minutes=30)).isoformat()}}
    db.add(m.Activity(kind='submission_reserved',title='Browser submission reserved',entity_type='application',entity_id=id,data={'resume_version_id':app.resume_version_id}));db.commit()
    return {'lease':lease,'expires_at':app.data['auto_apply']['expires_at'],'resume_version_id':app.resume_version_id,'application_id':id}

def stop(db,id,state):
    if state not in {'revoked','uncertain'}:raise ValueError('Invalid queue state.')
    app=db.get(m.Application,id)
    if not app:raise ValueError('Application not found.')
    approval=(app.data or {}).get('auto_apply',{})
    if approval.get('state')=='submitted':raise ValueError('A submitted application cannot be reset.')
    if state=='revoked' and approval.get('state') in {'in_progress','uncertain'}:raise ValueError('Review the employer receipt before resolving this attempt.')
    app.data={**app.data,'auto_apply':{**approval,'state':state}}
    db.commit();return {'state':state}
