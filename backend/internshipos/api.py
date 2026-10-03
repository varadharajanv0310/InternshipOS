"""Single-user JSON API. Product operations persist through the domain services."""
import hmac, os, re, secrets
from datetime import datetime, timezone
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session,joinedload
from .db import get_db, utcnow
from .auth import require_owner, sign_token, read_token, PASSWORD, COOKIE
from . import service, resumes, integrations, ai
from .models import Company, CompanySource, ResumeVersion, Project, Activity, EmailMessage, Task, CalendarLink, Notification, Application, Setting
from .serialize import row_dict, source_dict, task_dict
from .jobs import enqueue, BackgroundJob, morning_digest

public=APIRouter(prefix='/api')
router=APIRouter(prefix='/api',dependencies=[Depends(require_owner)])

class Login(BaseModel):password:str=Field(max_length=1000)
@public.get('/auth/status')
def auth_status(request:Request):
    token=read_token(request.cookies.get(COOKIE,''))
    return {'requires_password':bool(PASSWORD),'authenticated':not PASSWORD or bool(token and token.get('scope')=='owner')}
@public.post('/auth/login')
def login(data:Login):
    if PASSWORD and not hmac.compare_digest(data.password,PASSWORD):raise HTTPException(401,'Incorrect workspace password.')
    response=JSONResponse({'authenticated':True});response.set_cookie(COOKIE,sign_token({'scope':'owner'}),httponly=True,samesite='lax',secure=os.getenv('PUBLIC_BASE_URL','').startswith('https:'),max_age=86400);return response
@public.post('/auth/logout')
def logout():
    response=JSONResponse({'authenticated':False});response.delete_cookie(COOKIE);return response

def must(value,message='Not found.'):
    if value is None:raise HTTPException(404,message)
    return value
def safe_url(value):
    parsed=urlparse(value or '')
    if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password:raise HTTPException(422,'Use a public HTTP or HTTPS page URL without embedded credentials.')
    return value

@router.get('/dashboard')
def dashboard(db:Session=Depends(get_db)):return service.dashboard(db)
@router.get('/opportunities')
def opportunities(q:str='',role:str='',location:str='',kind:str='internship',saved:bool|None=None,min_fit:int|None=None,min_worth:int|None=None,technical:bool=True,work_mode:str='',eligibility:str='',source:str='',risk:str='',fresh_days:int|None=None,application_stage:str='',pay:str='',sort:str='company_priority',page:int=1,page_size:int=40,db:Session=Depends(get_db)):
    return service.list_opportunities(db,q=q,role=role,location=location,kind=kind,saved=saved,min_fit=min_fit,min_worth=min_worth,technical=technical,work_mode=work_mode,eligibility=eligibility,source=source,risk=risk,fresh_days=fresh_days,application_stage=application_stage,pay=pay,sort=sort,page=max(1,page),page_size=max(1,min(page_size,100)))
@router.get('/opportunities/{id}')
def opportunity(id:str,db:Session=Depends(get_db)):return must(service.get_opportunity(db,id))
@router.patch('/opportunities/{id}')
def save_opportunity(id:str,payload:dict,db:Session=Depends(get_db)):return service.save_opportunity(db,id,payload)
@router.get('/applications')
def applications(db:Session=Depends(get_db)):return service.list_applications(db)
@router.post('/applications',status_code=201)
def application_create(payload:dict,db:Session=Depends(get_db)):return service.create_application(db,payload)
@router.patch('/applications/{id}')
def application_update(id:str,payload:dict,db:Session=Depends(get_db)):return service.update_application(db,id,payload)
@router.get('/applications/{id}/pack')
def pack(id:str,db:Session=Depends(get_db)):return resumes.preparation_pack(db,id)
@router.get('/tasks')
def tasks(db:Session=Depends(get_db)):return service.list_tasks(db)
@router.post('/tasks',status_code=201)
def task_create(payload:dict,db:Session=Depends(get_db)):return service.save_task(db,payload)
@router.patch('/tasks/{id}')
def task_update(id:str,payload:dict,db:Session=Depends(get_db)):return service.save_task(db,payload,id)
@router.get('/companies')
def companies(q:str='',db:Session=Depends(get_db)):return service.list_companies(db,q=q)
@router.get('/companies/{id}')
def company(id:str,db:Session=Depends(get_db)):return must(service.company_detail(db,id))
@router.patch('/companies/{id}')
def company_review(id:str,payload:dict,db:Session=Depends(get_db)):
    row=must(db.get(Company,id));before=row_dict(row)
    if 'company_priority' in payload:
        score=payload['company_priority'];reason=str(payload.get('priority_reason','')).strip()
        if isinstance(score,bool) or not isinstance(score,int) or not 0<=score<=100 or len(reason)<8:raise HTTPException(422,'Supply a company priority from 0 to 100 and a reason.')
        row.metadata_json={**row.metadata_json,'company_priority':{'score':score,'tier':'Your preference','reason':reason,'source':'owner'}}
        if set(payload)<= {'company_priority','priority_reason'}:
            db.add(Activity(kind='company_priority',title='Company preference updated',entity_type='company',entity_id=id,before=before,after={'company_priority':score,'reason':reason}));db.commit();return service.company_detail(db,id)
    if payload.get('verified'):
        if len(str(payload.get('verification_reason','')).strip())<8:raise HTTPException(422,'Record why this is the official employer identity.')
        safe_url(payload.get('verification_url'))
    if 'domain' in payload:
        raw=str(payload['domain'] or '').strip();row.domain=urlparse(raw if '://' in raw else 'https://'+raw).hostname if raw else None
    if 'careers_url' in payload:row.careers_url=safe_url(payload['careers_url']) if payload['careers_url'] else None
    if 'verified' in payload:row.verified=bool(payload['verified'])
    row.metadata_json={**row.metadata_json,'identity_review':{'reason':payload.get('verification_reason'),'url':payload.get('verification_url'),'at':utcnow().isoformat()},'discovery':{}}
    db.add(Activity(kind='company_review',title='Employer identity reviewed',entity_type='company',entity_id=id,before=before,after={'domain':row.domain,'verified':row.verified},data=row.metadata_json['identity_review']));db.commit();return service.company_detail(db,id)
@router.get('/analytics')
def analytics(days:int=30,scope:str='india',db:Session=Depends(get_db)):
    from .backup import backup_status
    data=service.analytics(db,days=max(7,min(days,365)),scope=scope);data['ai_usage']=ai.budget_status(db);data['backup_health']=backup_status(db)
    heartbeat=db.get(Setting,'worker_heartbeat');data['worker_health']=heartbeat.value if heartbeat else {'at':None}
    return data
@router.get('/activity')
def activity(db:Session=Depends(get_db)):return service.list_activity(db)
@router.post('/activity/{id}/undo')
def undo(id:str,db:Session=Depends(get_db)):return service.undo_activity(db,id)
@router.get('/profile')
def profile(db:Session=Depends(get_db)):return service.get_profile(db)
@router.patch('/profile')
def profile_save(payload:dict,db:Session=Depends(get_db)):
    forbidden={'address','cookies','password','passport','aadhaar','identity_documents','sensitive_answers'}
    if forbidden&payload.keys():raise HTTPException(422,'Sensitive identity, address and browser-session answers belong in local extension storage.')
    return service.save_profile(db,payload)
@router.get('/settings')
def settings(db:Session=Depends(get_db)):return {**service.get_settings(db),'ai_usage':ai.budget_status(db)}
@router.patch('/settings')
def settings_save(payload:dict,db:Session=Depends(get_db)):
    if 'ai_monthly_budget' in payload:payload['ai_monthly_budget_usd']=payload.pop('ai_monthly_budget')
    budget=payload.get('ai_monthly_budget_usd')
    if budget is not None and (not isinstance(budget,(int,float)) or budget<0 or budget>3):raise HTTPException(422,'The personal AI budget must stay between $0 and $3 per month.')
    auto=payload.get('auto_apply',{})
    if auto.get('enabled') and not auto.get('providers'):raise HTTPException(422,'Select the specific supported form categories you authorize for auto-apply.')
    return service.save_settings(db,payload)

@router.get('/sources')
def sources(db:Session=Depends(get_db)):
    rows=db.scalars(select(CompanySource).options(joinedload(CompanySource.company)).order_by(CompanySource.priority,CompanySource.provider)).all();items=[]
    for row in rows:
        data=source_dict(row);company=db.get(Company,row.company_id);data['company_name']=company.name if company else '';items.append(data)
    jobs=[row_dict(j) for j in db.scalars(select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(8)).all()]
    return {'items':items,'total':len(items),'jobs':jobs}
@router.post('/sources/collect',status_code=202)
def collect(payload:dict|None=None,db:Session=Depends(get_db)):
    payload=payload or {};return enqueue(db,'collect',{'source_ids':payload.get('source_ids'),'limit':min(int(payload.get('limit',12)),30),'force':bool(payload.get('force',True))})
@router.post('/sources/discover',status_code=202)
def discover(db:Session=Depends(get_db)):return enqueue(db,'discover')
@router.post('/sources',status_code=201)
def source_create(payload:dict,db:Session=Depends(get_db)):
    url=safe_url(payload.get('url'));name=str(payload.get('company_name','')).strip()
    if not name:raise HTTPException(422,'Provide an employer name.')
    company=db.scalars(select(Company).where(Company.name==name)).first()
    if not company:company=Company(name=name,domain=payload.get('domain'),verified=False);db.add(company);db.flush()
    row=CompanySource(company_id=company.id,provider=payload.get('provider','html'),url=url,tenant=payload.get('tenant'),board=payload.get('board'),config=payload.get('config',{}),priority=int(payload.get('priority',2)),cadence_hours=float(payload.get('cadence_hours',24)),verified=False,enabled=True);db.add(row);db.add(Activity(kind='source_added',title='New employer source added',entity_type='company',entity_id=company.id,data={'url':url}));db.commit();return source_dict(row)
@router.patch('/sources/{id}')
def source_control(id:str,payload:dict,db:Session=Depends(get_db)):
    row=must(db.get(CompanySource,id));before={'enabled':row.enabled,'cadence_hours':row.cadence_hours,'priority':row.priority}
    if 'verified' in payload:
        if not isinstance(payload['verified'],bool):raise HTTPException(422,'Verification must be true or false.')
        if payload['verified']:
            reason=str(payload.get('verification_reason','')).strip();url=safe_url(payload.get('verification_url'))
            domain=(row.company.domain or '').lower().removeprefix('www.');host=(urlparse(url).hostname or '').lower().removeprefix('www.')
            if not row.company.verified or not domain or not (host==domain or host.endswith('.'+domain)) or len(reason)<8:
                raise HTTPException(422,'Verify the employer identity and cite its official website linking to this board, with a reason.')
            row.config={**row.config,'association_status':'verified','association_evidence':{'kind':'owner_review','linked_from':url,'target':row.url,'reason':reason,'checked_at':utcnow().isoformat()}}
        else:row.config={**row.config,'association_status':'candidate'}
        row.verified=payload['verified']
    if 'enabled' in payload:row.enabled=bool(payload['enabled'])
    if 'cadence_hours' in payload:
        hours=float(payload['cadence_hours'])
        if not 1<=hours<=168:raise HTTPException(422,'Source cadence must be between 1 and 168 hours.')
        row.cadence_hours=hours;row.config={**row.config,'cadence_override':True}
    if 'priority' in payload:
        priority=int(payload['priority'])
        if priority not in (1,2,3):raise HTTPException(422,'Choose priority 1, 2 or 3.')
        row.priority=priority
    db.add(Activity(kind='source_control',title='Source monitoring updated',entity_type='source',entity_id=id,before=before,after={'enabled':row.enabled,'cadence_hours':row.cadence_hours,'priority':row.priority,'verified':row.verified},data={'association_evidence':row.config.get('association_evidence')}));db.commit();return source_dict(row)
@router.post('/capture',status_code=201)
def capture(payload:dict,db:Session=Depends(get_db)):
    url=safe_url(payload.get('url'));title=str(payload.get('title','')).strip()
    if not title:raise HTTPException(422,'Add the job title before saving.')
    hostname=urlparse(url).hostname;company_name=str(payload.get('company_name') or payload.get('company') or hostname).strip()
    company=db.scalars(select(Company).where(Company.name==company_name)).first()
    if not company:company=Company(name=company_name,domain=payload.get('company_domain'),verified=False);db.add(company);db.flush()
    source=db.scalars(select(CompanySource).where(CompanySource.company_id==company.id,CompanySource.provider=='capture')).first()
    if not source:source=CompanySource(company_id=company.id,provider='capture',url=url,enabled=False,verified=False,config={},cadence_hours=24);db.add(source);db.flush()
    import hashlib
    job={'external_id':hashlib.sha256(url.encode()).hexdigest(),'title':title,'company_name':company_name,'description':str(payload.get('description',''))[:100000],'location':payload.get('location','Unknown'),'canonical_url':url,'apply_url':payload.get('apply_url',url),'raw':payload,'evidence':{'method':'user_capture','url':url},'employment_type':payload.get('employment_type','internship')}
    db.commit();return service.ingest_batch(db,source.id,[job],complete=False,coverage_scope='capture',observed_count=1)

@router.get('/notifications')
def notifications(db:Session=Depends(get_db)):
    items=[row_dict(n) for n in db.scalars(select(Notification).order_by(Notification.created_at.desc()).limit(80)).all()];return {'items':items,'total':len(items)}
@router.patch('/notifications/{id}')
def notification_read(id:str,payload:dict,db:Session=Depends(get_db)):
    row=must(db.get(Notification,id));row.read=bool(payload.get('read',True));db.commit();return row_dict(row)
@router.post('/digest')
def digest(db:Session=Depends(get_db)):return morning_digest(db)

@router.get('/backup/status')
def backup_health(db:Session=Depends(get_db)):
    from .backup import backup_status
    return backup_status(db)
@router.get('/backup/export')
def backup_export(db:Session=Depends(get_db)):
    from .backup import create_backup
    path=create_backup(db)
    return FileResponse(path,media_type='application/zip',filename=path.name)

@router.get('/resumes')
def resume_list(db:Session=Depends(get_db)):return resumes.resume_inventory(db)
@router.post('/resumes',status_code=201)
def resume_create(payload:dict,db:Session=Depends(get_db)):return resumes.create_resume(db,payload)
@router.post('/resumes/{id}/versions',status_code=201)
def version_create(id:str,payload:dict,db:Session=Depends(get_db)):return resumes.create_version(db,id,payload)
@router.get('/resume-versions/{id}/preview',response_class=HTMLResponse)
def version_preview(id:str,db:Session=Depends(get_db)):return resumes.render_html(must(db.get(ResumeVersion,id)))
@router.get('/resume-versions/{id}/download')
def version_download(id:str,db:Session=Depends(get_db)):
    version=must(db.get(ResumeVersion,id));path=resumes.pdf_artifact(db,version);return FileResponse(path,media_type='application/pdf',filename='InternshipOS-resume-'+id[:8]+'.pdf')
@router.post('/projects/github')
def github_import(payload:dict,db:Session=Depends(get_db)):return resumes.github_inventory(db,str(payload.get('username','')))
@router.post('/projects',status_code=201)
def project_create(payload:dict,db:Session=Depends(get_db)):
    if not payload.get('name'):raise HTTPException(422,'Provide a project name.')
    project=Project(name=payload['name'],description=payload.get('description',''),technologies=payload.get('technologies',[]),approved=bool(payload.get('approved',False)),approved_bullets=payload.get('approved_bullets',[]),role_tags=payload.get('role_tags',[]),github_url=payload.get('github_url'),data={});db.add(project);db.commit();return row_dict(project)
@router.patch('/projects/{id}')
def project_save(id:str,payload:dict,db:Session=Depends(get_db)):
    project=must(db.get(Project,id))
    for k in ('name','description','technologies','approved','approved_bullets','role_tags'):
        if k in payload:setattr(project,k,payload[k])
    db.add(Activity(kind='project_review',title='Project facts reviewed',entity_type='project',entity_id=id,data={'approved':project.approved}));db.commit();return row_dict(project)
@router.post('/ai/{action}')
def ai_action(action:str,payload:dict,db:Session=Depends(get_db)):
    if action not in ('analyze','tailor','answer','cover-letter'):raise HTTPException(404,'Unknown intelligence action.')
    op=must(service.get_opportunity(db,payload.get('opportunity_id')),'Select an opportunity first.')
    compact={k:op.get(k) for k in ('id','title','company','role_family','location','work_mode','requirements','skills','compensation','eligibility','risk_reasons','evaluation','sources')}
    compact['description']=op.get('description','')[:12000]
    context={'opportunity':compact,'facts':resumes.facts_inventory(db),'question':str(payload.get('question',''))[:4000],'resume_id':payload.get('resume_id')}
    return ai.grounded_response(db,action,context,strong=True)

@router.get('/integrations')
def integration_list(db:Session=Depends(get_db)):return integrations.integration_status(db)
@router.get('/integrations/google/connect')
def google_connect():
    state=sign_token({'scope':'google_oauth','nonce':secrets.token_urlsafe(24)},600)
    response=RedirectResponse(integrations.authorization_url(state));response.set_cookie('ios_oauth_state',state,httponly=True,samesite='lax',secure=os.getenv('PUBLIC_BASE_URL','').startswith('https:'),max_age=600);return response
@router.get('/integrations/google/callback')
def google_callback(request:Request,state:str='',code:str='',error:str='',db:Session=Depends(get_db)):
    token=read_token(state)
    if not token or token.get('scope')!='google_oauth' or not hmac.compare_digest(request.cookies.get('ios_oauth_state',''),state):raise HTTPException(400,'The account connection expired. Start again from Settings.')
    if error:raise HTTPException(400,'Google connection was cancelled: '+error)
    integrations.exchange_code(db,code);response=RedirectResponse(os.getenv('FRONTEND_URL','http://127.0.0.1:5173').rstrip('/')+'/#/settings?connected=google');response.delete_cookie('ios_oauth_state');return response
@router.post('/integrations/google/poll')
def gmail_poll(db:Session=Depends(get_db)):return integrations.poll_gmail(db)
@router.post('/integrations/google/disconnect')
def gmail_disconnect(db:Session=Depends(get_db)):return integrations.disconnect_google(db)
@router.get('/emails/review')
def email_review(db:Session=Depends(get_db)):
    items=[{**row_dict(e),'snippet':e.body[:600],'original_url':'https://mail.google.com/mail/u/0/#all/'+str(e.thread_id or e.provider_message_id)} for e in db.scalars(select(EmailMessage).where(EmailMessage.status=='review').order_by(EmailMessage.received_at.desc())).all()];return {'items':items,'total':len(items)}
@router.post('/emails/{id}/match')
def email_match(id:str,payload:dict,db:Session=Depends(get_db)):
    email=must(db.get(EmailMessage,id));kind=payload.get('event_type') or email.data.get('classification',{}).get('event_type','unknown');kind={'applied':'confirmation','oa':'assessment','rejected':'rejection'}.get(kind,kind);return integrations.apply_email_event(db,email,payload.get('application_id'),kind,manual=True)
@router.post('/calendar/sync')
def calendar_sync(db:Session=Depends(get_db)):return integrations.calendar_sync(db)
@router.get('/calendar')
def calendar(db:Session=Depends(get_db)):
    tasks=service.list_tasks(db)['items'];links={l.task_id:row_dict(l) for l in db.scalars(select(CalendarLink)).all()}
    return {'items':[{**t,'start_at':t.get('due_at'),'calendar_link':links.get(t['id'])} for t in tasks],'total':len(tasks),'time_zone':service.get_settings(db).get('timezone','Asia/Kolkata')}

@router.post('/extension/pair')
def extension_pair():return {'token':sign_token({'scope':'extension'},86400*30),'expires_days':30,'api_url':os.getenv('PUBLIC_BASE_URL','http://127.0.0.1:8000')+'/api'}
@router.get('/extension/applications')
def extension_applications(db:Session=Depends(get_db)):
    items=service.list_applications(db)['items'];return {'items':[{'id':a['id'],'title':a['opportunity']['title'],'company':a['opportunity']['company']['name'],'stage':a['stage']} for a in items]}
@router.get('/extension/pack')
def extension_pack(application_id:str,db:Session=Depends(get_db)):return resumes.preparation_pack(db,application_id)
@router.post('/extension/receipt')
def receipt(payload:dict,db:Session=Depends(get_db)):
    app=must(db.get(Application,payload.get('application_id')))
    op=service.get_opportunity(db,app.opportunity_id);url=payload.get('url','');evidence=str(payload.get('evidence',''))[:2000]
    target=urlparse(op.get('apply_url') or op.get('canonical_url') or '').hostname
    approval=(app.data or {}).get('auto_apply',{})
    if payload.get('lease'):
        from .application_queue import fingerprint
        if approval.get('state') not in {'in_progress','uncertain'} or not hmac.compare_digest(str(approval.get('lease','')),str(payload['lease'])) or payload.get('resume_version_id')!=approval.get('resume_version_id'):raise HTTPException(422,'Receipt does not match the approved application attempt.')
    elif approval.get('state') in {'in_progress','uncertain'}:raise HTTPException(422,'Use the original submission lease to confirm this attempt.')
    if urlparse(url).hostname!=target or not re.search(r'application (received|submitted)|thank you for applying|thanks for applying|successfully submitted',evidence,re.I):raise HTTPException(422,'A supported submission receipt was not detected. Confirm manually only after successful submission.')
    changes={'stage':'applied','resume_version_id':None} if app.stage=='ready' else {}
    if payload.get('resume_version_id'):
        version=must(db.get(ResumeVersion,payload['resume_version_id']))
        if version.status!='approved':raise HTTPException(422,'Only an approved resume version can be recorded as submitted.')
        changes['resume_version_id']=version.id
    result=service.update_application(db,app.id,changes)
    if payload.get('lease'):app.data={**app.data,'auto_apply':{**approval,'state':'submitted'}}
    db.add(Activity(kind='submission_receipt',title='Application receipt captured',entity_type='application',entity_id=app.id,data={'url':url,'receipt_text':evidence,'resume_version_id':payload.get('resume_version_id')}));db.commit();return result


@router.get('/application-queue')
def application_queue(db:Session=Depends(get_db)):
    from .application_queue import listing
    return listing(db)

@router.post('/application-queue/{id}/approve')
def queue_approve(id:str,payload:dict,db:Session=Depends(get_db)):
    from .application_queue import approve
    if payload.get('confirm') is not True:raise HTTPException(422,'Review and explicitly approve this application.')
    return approve(db,id,payload.get('eligibility_reviewed') is True)

@router.post('/application-queue/{id}/revoke')
def queue_revoke(id:str,db:Session=Depends(get_db)):
    from .application_queue import stop
    return stop(db,id,'revoked')

@router.get('/extension/queue')
def extension_queue(db:Session=Depends(get_db)):
    from .application_queue import listing
    return listing(db)

@router.post('/extension/claim')
def extension_claim(payload:dict,db:Session=Depends(get_db)):
    from .application_queue import claim
    return claim(db,payload.get('application_id'))

@router.post('/extension/attempt-stopped')
def attempt_stopped(payload:dict,db:Session=Depends(get_db)):
    from .application_queue import stop
    app=must(db.get(Application,payload.get('application_id')))
    approval=(app.data or {}).get('auto_apply',{})
    if not hmac.compare_digest(str(approval.get('lease','')),str(payload.get('lease',''))) or not approval.get('lease'):raise HTTPException(422,'Submission lease mismatch.')
    return stop(db,app.id,'uncertain')
