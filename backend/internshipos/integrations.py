"""First-party Google OAuth, read-only recruiting mail and an app-owned calendar."""
import base64, hashlib, json, os, re, secrets
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import urlencode, quote
import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select
from .db import utcnow, aware
from .models import Integration, EmailMessage, EmailLink, Application, ApplicationEvent, Task, CalendarLink, Activity, Notification
from . import service
from .serialize import iso

SCOPES=['https://www.googleapis.com/auth/gmail.readonly','https://www.googleapis.com/auth/calendar.app.created']
STAGES={'confirmation':'applied','assessment':'oa','interview':'interview','offer':'offer','rejection':'rejected'}
TRUSTED_SENDERS=('greenhouse.io','greenhouse-mail.io','lever.co','myworkday.com','myworkdayjobs.com','smartrecruiters.com','ashbyhq.com','icims.com','oraclecloud.com')

def cipher():
    key=os.getenv('TOKEN_ENCRYPTION_KEY')
    if not key:
        folder=Path(os.getenv('APP_DATA_DIR','data'));folder.mkdir(parents=True,exist_ok=True)
        path=folder/'token.key'
        if not path.exists():
            try:
                with path.open('xb') as f:f.write(Fernet.generate_key())
            except FileExistsError:pass
        key=path.read_bytes()
    return Fernet(key.encode() if isinstance(key,str) else key)

def google_row(db):
    return db.scalars(select(Integration).where(Integration.provider=='google')).first()

def integration_status(db):
    row=google_row(db)
    return {'items':[
        {'provider':'google','configured':bool(os.getenv('GOOGLE_CLIENT_ID') and os.getenv('GOOGLE_CLIENT_SECRET')),'connected':bool(row and row.credentials_encrypted),'status':row.status if row else 'disconnected','data':row.data if row else {},'scopes':SCOPES},
        {'provider':'github','configured':True,'connected':bool(db.scalars(select(Integration).where(Integration.provider=='github')).first()),'status':'public import available'},
        {'provider':'ai','configured':__import__('internshipos.providers',fromlist=['provider_configured']).provider_configured(),'connected':__import__('internshipos.providers',fromlist=['provider_configured']).provider_configured(),'status':'optional'},
    ]}

def authorization_url(state):
    client=os.getenv('GOOGLE_CLIENT_ID')
    if not client or not os.getenv('GOOGLE_CLIENT_SECRET'):raise HTTPException(409,'Add your own Google OAuth client ID and secret in the server environment to connect Gmail and Calendar.')
    redirect=os.getenv('GOOGLE_REDIRECT_URI',os.getenv('PUBLIC_BASE_URL','http://127.0.0.1:8000')+'/api/integrations/google/callback')
    return 'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({'client_id':client,'redirect_uri':redirect,'response_type':'code','scope':' '.join(SCOPES),'access_type':'offline','prompt':'consent','state':state,'include_granted_scopes':'true'})

def exchange_code(db,code):
    redirect=os.getenv('GOOGLE_REDIRECT_URI',os.getenv('PUBLIC_BASE_URL','http://127.0.0.1:8000')+'/api/integrations/google/callback')
    with httpx.Client(timeout=25) as client:
        response=client.post('https://oauth2.googleapis.com/token',data={'code':code,'client_id':os.getenv('GOOGLE_CLIENT_ID'),'client_secret':os.getenv('GOOGLE_CLIENT_SECRET'),'redirect_uri':redirect,'grant_type':'authorization_code'})
        if response.status_code!=200:raise HTTPException(400,'Google could not complete the connection. Reconnect with the configured redirect URI.')
        credentials=response.json()
    row=google_row(db)
    if not row:row=Integration(provider='google');db.add(row)
    if not credentials.get('refresh_token') and row.credentials_encrypted:
        old=json.loads(cipher().decrypt(row.credentials_encrypted.encode()));credentials['refresh_token']=old.get('refresh_token')
    if not credentials.get('refresh_token'):raise HTTPException(400,'A refresh token was not provided. Reconnect and grant offline read-only access.')
    credentials['expires_at']=utcnow().timestamp()+credentials.get('expires_in',3600)
    row.credentials_encrypted=cipher().encrypt(json.dumps(credentials).encode()).decode();row.status='connected';row.data={**(row.data or {}),'connected_at':utcnow().isoformat()}
    db.add(Activity(kind='integration',title='Gmail and Calendar connected',entity_type='integration',entity_id=row.id,data={'scopes':SCOPES}));db.commit()

def access_token(db,row):
    if not row or not row.credentials_encrypted:raise HTTPException(409,'Connect your Google account first.')
    credentials=json.loads(cipher().decrypt(row.credentials_encrypted.encode()))
    if credentials.get('expires_at',0)<utcnow().timestamp()+90:
        with httpx.Client(timeout=25) as client:
            response=client.post('https://oauth2.googleapis.com/token',data={'client_id':os.getenv('GOOGLE_CLIENT_ID'),'client_secret':os.getenv('GOOGLE_CLIENT_SECRET'),'refresh_token':credentials['refresh_token'],'grant_type':'refresh_token'})
        if response.status_code!=200:
            row.status='needs_reconnect';db.commit();raise HTTPException(409,'Google access expired or was revoked. Reconnect in Settings.')
        fresh=response.json();credentials.update(fresh);credentials['expires_at']=utcnow().timestamp()+fresh.get('expires_in',3600)
        row.credentials_encrypted=cipher().encrypt(json.dumps(credentials).encode()).decode();db.commit()
    return credentials['access_token']

def classify_email(subject,body):
    text=(subject+'\n'+body).lower()
    patterns=[('cancellation',r'(interview|call).{0,80}(cancelled|canceled)|cancelled.{0,50}interview'),('reschedule',r'reschedul|new interview time'),('rejection',r'not (?:be )?(?:moving|proceeding|selected)|unfortunately.{0,140}(?:application|position|candidate)|regret to inform|other candidates|not been selected'),('offer',r'offer (?:letter|of employment)|pleased to offer|internship offer'),('assessment',r'online assessment|assessment invitation|coding (?:test|challenge)|complete.{0,50}assessment'),('interview',r'interview (?:invitation|scheduled|confirmation)|invite.{0,60}interview|schedule.{0,60}interview'),('documents',r'(?:additional|required|submit|upload).{0,45}(?:documents|transcript|identity document)'),('confirmation',r'application (?:received|submitted|confirmed)|thank you for applying|thanks for applying|received your application'),('recruiter',r'recruiter|talent acquisition|discuss.{0,50}(?:role|opportunity)')]
    for kind,pattern in patterns:
        m=re.search(pattern,text,re.S)
        if m:return {'event_type':kind,'evidence':m.group(0),'confidence':'high' if kind not in ('recruiter','documents') else 'medium'}
    return {'event_type':'unknown','evidence':'','confidence':'low'}

def matching_candidates(applications,sender,subject,body):
    domain=parseaddr(sender)[1].lower().split('@')[-1]
    text=(subject+' '+body).lower();candidates=[]
    for app in applications:
        op=app['opportunity'];company=op.get('company',{});company_domain=(company.get('domain') or '').lower().removeprefix('www.')
        trusted=bool(company_domain and (domain==company_domain or domain.endswith('.'+company_domain))) or any(domain==d or domain.endswith('.'+d) for d in TRUSTED_SENDERS)
        if not trusted:continue
        identity=bool(op.get('canonical_url') and op['canonical_url'].lower() in text)
        company_named=bool(company.get('name') and re.search(r'\b'+re.escape(company['name'].lower())+r'\b',text))
        requisitions=[op.get('requisition_id')]+[s.get('requisition_id') or s.get('external_id') for s in op.get('sources',[])]
        req_match=any(r and len(str(r))>=4 and re.search(r'(?<![\w])'+re.escape(str(r).lower())+r'(?![\w])',text) for r in requisitions)
        exact_title=bool(op.get('title') and op['title'].lower() in text)
        if identity or (company_named and (req_match or exact_title)):
            candidates.append({'application_id':app['id'],'reason':'canonical link' if identity else 'company and requisition/title'})
    return candidates

def _decode_part(payload):
    if payload.get('mimeType')=='text/plain' and payload.get('body',{}).get('data'):
        raw=payload['body']['data'];return base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)).decode(errors='replace')
    text='\n'.join(_decode_part(p) for p in payload.get('parts',[]))
    if text.strip():return text
    if payload.get('body',{}).get('data'):
        raw=payload['body']['data'];value=base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)).decode(errors='replace')
        return re.sub('<[^>]+>',' ',value)
    return ''

def exact_email_time(text):
    # Only explicit ISO date-time with an offset is admitted automatically.
    match=re.search(r'\b(20\d{2}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2}))\b',text)
    if not match:return None
    try:return datetime.fromisoformat(match.group(1).replace('Z','+00:00')).astimezone(timezone.utc)
    except ValueError:return None

def apply_email_event(db,email,application_id,event_type,manual=False):
    app=db.get(Application,application_id)
    if not app:raise HTTPException(404,'Application not found.')
    prior=db.scalars(select(EmailLink).where(EmailLink.email_message_id==email.id,EmailLink.application_id==app.id,EmailLink.event_type==event_type)).first()
    if prior and not prior.data.get('undone'):return {'status':'already_linked','application_id':app.id}
    old=app.stage;old_submitted=app.submitted_at;new=STAGES.get(event_type,old)
    if event_type not in set(STAGES)|{'documents','reschedule','cancellation','recruiter','unknown'}:raise HTTPException(422,'Unknown recruiting event type.')
    rank={'ready':0,'applied':1,'oa':2,'interview':3,'offer':4,'rejected':4}
    if not manual and (old in ('offer','rejected') or (new!='rejected' and rank.get(new,0)<rank.get(old,0))):new=old
    if prior:prior.data={'manual':manual,'evidence':email.data.get('classification',{}),'undone':False}
    else:db.add(EmailLink(email_message_id=email.id,application_id=app.id,event_type=event_type,data={'manual':manual,'evidence':email.data.get('classification',{})}))
    email.status='matched';app.stage=new
    if new!='ready' and app.submitted_at is None:app.submitted_at=email.received_at or utcnow()
    revision=':'+utcnow().isoformat() if prior else ''
    db.add(ApplicationEvent(application_id=app.id,event_type=event_type,from_stage=old,to_stage=new,source='gmail_review' if manual else 'gmail',occurred_at=email.received_at or utcnow(),dedupe_key='mail:'+email.provider_message_id+':'+event_type+revision,data={'email_id':email.id}))
    audit=Activity(kind='email_match',title=email.subject,body='Recruiting email linked to an application',entity_type='application',entity_id=app.id,before={'stage':old,'submitted_at':iso(old_submitted)},after={'stage':new,'submitted_at':iso(app.submitted_at)},data={'email_id':email.id,'event_type':event_type,'automatic':not manual})
    db.add(audit);cancelled=[];created=[]
    due=exact_email_time(email.body)
    if event_type in ('assessment','interview','offer','documents','reschedule','cancellation','recruiter'):
        if event_type in ('reschedule','cancellation'):
            for task in db.scalars(select(Task).where(Task.application_id==app.id,Task.kind=='interview',Task.completed==False)).all():
                cancelled.append({'id':task.id,'completed':task.completed,'data':task.data})
                task.completed=True;task.data={**task.data,'cancelled':True,'email_id':email.id}
        if event_type!='cancellation':
            task=Task(title=f"{event_type.title()}: {app.opportunity.title}",application_id=app.id,opportunity_id=app.opportunity_id,kind='interview' if event_type=='reschedule' else event_type,due_at=due,date_precision='exact' if due else 'unknown',dedupe_key='email-task:'+email.id+':'+app.id+revision,notes='Review date/time in the original message.' if not due else '',data={'email_id':email.id})
            db.add(task);db.flush();created.append(task.id)
    audit.data={**audit.data,'created_task_ids':created,'cancelled_tasks':cancelled}
    db.add(Notification(title=event_type.title()+' update',body=email.subject,kind='recruiting',data={'application_id':app.id,'email_id':email.id}));db.commit()
    return {'status':'matched','application_id':app.id,'stage':new,'needs_time_review':due is None}

def poll_gmail(db):
    row=google_row(db);token=access_token(db,row);data=dict(row.data or {});ids=[];complete=True;resync=False
    with httpx.Client(timeout=30,headers={'Authorization':'Bearer '+token}) as client:
        base='https://gmail.googleapis.com/gmail/v1/users/me'
        start_id=data.get('history_id')
        if start_id:
            params={'startHistoryId':start_id,'historyTypes':'messageAdded','maxResults':100}
            if data.get('history_page'):params['pageToken']=data['history_page']
            latest=start_id
            for _ in range(5):
                response=client.get(base+'/history',params=params)
                if response.status_code==404:start_id=None;resync=True;break
                response.raise_for_status();page=response.json();latest=page.get('historyId',latest)
                for item in page.get('history',[]):
                    ids.extend(m['message']['id'] for m in item.get('messagesAdded',[]))
                if not page.get('nextPageToken'):data.pop('history_page',None);break
                params['pageToken']=page['nextPageToken'];data['history_page']=page['nextPageToken']
            else:complete=False
            if start_id and complete:data['history_id']=latest
        if not start_id:
            profile=client.get(base+'/profile');profile.raise_for_status();cursor=profile.json()['historyId']
            response=client.get(base+'/messages',params={'q':'newer_than:14d (application OR interview OR assessment OR recruiter OR offer)','maxResults':50});response.raise_for_status()
            page=response.json();ids=[m['id'] for m in page.get('messages',[])]
            data.update(history_id=cursor,initial_import_limited=bool(page.get('nextPageToken')),resynced=resync)
        existing=set(db.scalars(select(EmailMessage.provider_message_id)).all());applications=service.list_applications(db)['items'];new=matched=review=0
        for message_id in dict.fromkeys(ids):
            if message_id in existing:continue
            response=client.get(base+'/messages/'+message_id,params={'format':'full'});response.raise_for_status();message=response.json()
            headers={h['name'].lower():h['value'] for h in message.get('payload',{}).get('headers',[])}
            body=_decode_part(message.get('payload',{}))[:24000];classification=classify_email(headers.get('subject',''),body)
            if classification['event_type']=='unknown':continue
            candidates=matching_candidates(applications,headers.get('from',''),headers.get('subject',''),body)
            email=EmailMessage(provider_message_id=message_id,thread_id=message.get('threadId'),sender=headers.get('from',''),subject=headers.get('subject',''),body=body,received_at=datetime.fromtimestamp(int(message.get('internalDate',0))/1000,timezone.utc),status='review',data={'classification':classification,'candidates':candidates})
            db.add(email);db.commit();new+=1
            if len(candidates)==1 and classification['confidence']=='high':apply_email_event(db,email,candidates[0]['application_id'],classification['event_type']);matched+=1
            else:review+=1
        row.data={**data,'last_polled_at':utcnow().isoformat(),'last_poll_counts':{'new':new,'matched':matched,'review':review,'complete':complete}};row.status='connected';db.commit()
    return row.data['last_poll_counts']

def disconnect_google(db):
    row=google_row(db)
    if row:
        if row.credentials_encrypted:
            try:
                creds=json.loads(cipher().decrypt(row.credentials_encrypted.encode()))
                with httpx.Client(timeout=15) as client:client.post('https://oauth2.googleapis.com/revoke',data={'token':creds.get('refresh_token')})
            except Exception:pass
        row.credentials_encrypted=None;row.status='disconnected';row.data={};db.commit()
    return {'status':'disconnected'}

def calendar_sync(db):
    row=google_row(db);token=access_token(db,row);data=dict(row.data or {});synced=review=0
    with httpx.Client(timeout=25,headers={'Authorization':'Bearer '+token}) as client:
        base='https://www.googleapis.com/calendar/v3'
        calendar_id=data.get('calendar_id')
        if not calendar_id:
            response=client.post(base+'/calendars',json={'summary':'InternshipOS','timeZone':'Asia/Kolkata','description':'Internship deadlines and confirmed recruiting events managed by InternshipOS.'});response.raise_for_status();calendar_id=response.json()['id'];data['calendar_id']=calendar_id;row.data=data;db.commit()
        tasks=db.scalars(select(Task).where(Task.due_at!=None,Task.date_precision.in_(['exact','timestamp','date']))).all()
        for task in tasks:
            link=db.scalars(select(CalendarLink).where(CalendarLink.task_id==task.id)).first()
            if not link:
                link=CalendarLink(task_id=task.id,external_id='ios'+hashlib.sha256(task.id.encode()).hexdigest()[:40]);db.add(link);db.commit()
            endpoint=base+'/calendars/'+quote(calendar_id,safe='')+'/events/'+link.external_id
            current=client.get(endpoint)
            if current.status_code not in (200,404,410):current.raise_for_status()
            if task.completed:
                if current.status_code==200:
                    if link.etag and current.json().get('etag')!=link.etag:link.status='needs_review';review+=1;continue
                    response=client.delete(endpoint,headers={'If-Match':link.etag} if link.etag else {});response.raise_for_status()
                link.status='cancelled';continue
            due=aware(task.due_at)
            if task.date_precision=='date':
                start={'date':due.date().isoformat()};end={'date':(due.date()+timedelta(days=1)).isoformat()}
            else:
                start={'dateTime':due.isoformat()};end={'dateTime':(due+timedelta(minutes=60 if task.kind=='interview' else 15)).isoformat()}
            payload={'summary':task.title,'description':task.notes or 'Managed by InternshipOS.','start':start,'end':end,'extendedProperties':{'private':{'internshipos_task':task.id}}}
            digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
            if current.status_code==200:
                if link.etag and current.json().get('etag')!=link.etag:link.status='needs_review';review+=1;continue
                if link.data.get('desired_hash')==digest:continue
                response=client.patch(endpoint,json=payload,headers={'If-Match':link.etag} if link.etag else {})
            else:response=client.post(base+'/calendars/'+quote(calendar_id,safe='')+'/events',json={**payload,'id':link.external_id})
            if response.status_code==412:link.status='needs_review';review+=1;continue
            response.raise_for_status();link.etag=response.json().get('etag');link.data={'desired_hash':digest,'calendar_id':calendar_id};link.status='synced';synced+=1
        row.data={**data,'last_calendar_sync':utcnow().isoformat()};db.commit()
    return {'synced':synced,'needs_review':review,'calendar_id':calendar_id}
