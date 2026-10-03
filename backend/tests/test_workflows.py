"""End-to-end personal workflows with isolated fixtures, no external accounts."""
import json
import io
import httpx
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from internshipos.db import Base,get_db,utcnow
from internshipos import models as m,service,resumes,integrations,auth,ai,backup
from internshipos.api import router,public
from internshipos.providers import Provider,get_provider

def uploaded_pdf():
    from reportlab.pdfgen.canvas import Canvas
    output=io.BytesIO();canvas=Canvas(output);canvas.drawString(50,750,'Test-only uploaded resume');canvas.save();return output.getvalue()

def test_uploaded_resume_survives_cache_loss_and_preserves_original(client,db,tmp_path):
    contents=uploaded_pdf()
    response=client.post('/api/resumes/upload',files={'file':('original resume.pdf',contents,'application/pdf')},data={'name':'Uploaded SWE'})
    assert response.status_code==201
    v=response.json();assert v['status']=='draft' and v['data']['source']=='upload'
    assert 'contents' not in client.get('/api/resumes').text
    download=client.get('/api/resume-versions/'+v['id']+'/download');assert download.content==contents
    for path in (tmp_path/'resumes').glob('*.pdf'):path.unlink()
    assert client.get('/api/resume-versions/'+v['id']+'/preview').content==contents
    assert client.post('/api/resume-versions/'+v['id']+'/approve').json()['status']=='approved'
    app=application(db);assert client.patch('/api/applications/'+app['id'],json={'resume_version_id':v['id']}).status_code==200
    assert client.get('/api/applications/'+app['id']+'/pack').json()['resume_version']['id']==v['id']

def test_upload_rejects_bad_files_and_extension_scope(client,db,monkeypatch):
    assert client.post('/api/resumes/upload',files={'file':('x.pdf',b'not a pdf','application/pdf')}).status_code==422
    assert client.post('/api/resumes/upload',files={'file':('x.exe',uploaded_pdf(),'application/pdf')}).status_code==422
    assert client.post('/api/resumes/upload',files={'file':('x.pdf',b'%PDF-'+b'x'*resumes.UPLOAD_MAX_BYTES,'application/pdf')}).status_code==413
    assert db.scalar(select(func.count()).select_from(m.ResumeArtifact))==0
    monkeypatch.setattr(auth,'PASSWORD','test-password')
    assert client.post('/api/resumes/upload',files={'file':('x.pdf',uploaded_pdf(),'application/pdf')},headers={'Authorization':'Bearer '+auth.sign_token({'scope':'extension'})}).status_code==401

def test_backup_restores_uploaded_pdf_from_database(db,tmp_path):
    contents=uploaded_pdf();saved=resumes.upload_resume(db,contents,'test.pdf');resumes.approve_upload(db,db.get(m.ResumeVersion,saved['id']))
    archive=backup.create_backup(db)
    other=create_engine('sqlite://');Base.metadata.create_all(other)
    with Session(other) as restored:
        backup.restore_backup(restored,archive)
        assert restored.get(m.ResumeArtifact,saved['id']).contents==contents
        assert resumes.pdf_artifact(restored,restored.get(m.ResumeVersion,saved['id'])).read_bytes()==contents
    other.dispose()

def test_github_pagination_connection_and_review_preservation(client,db,monkeypatch):
    original=httpx.Client;requests=[]
    def handler(request):
        requests.append(str(request.url))
        if request.url.path.endswith('/readme'):return httpx.Response(404)
        page=int(request.url.params.get('page','1'))
        if page==1:return httpx.Response(200,json=[{'id':i,'name':'repo-'+str(i),'language':'Python','fork':i!=0} for i in range(100)])
        return httpx.Response(200,json=[{'id':101,'name':'final-project','language':'TypeScript'}])
    monkeypatch.setattr(resumes.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    result=resumes.github_inventory(db,'fixture');assert result['imported']==2 and any('page=2' in x for x in requests)
    project=db.scalar(select(m.Project).where(m.Project.name=='repo-0'));project.approved=True;project.description='Owner-reviewed';project.approved_bullets=['Built a tested project.'];db.commit()
    resumes.github_inventory(db,'fixture');assert project.approved and project.description=='Owner-reviewed' and project.approved_bullets==['Built a tested project.']
    assert client.get('/api/integrations').json()['items'][1]['data']['username']=='fixture'
    assert client.post('/api/projects/github/disconnect').status_code==200
    assert client.get('/api/integrations').json()['items'][1]['connected'] is False
    assert db.scalar(select(func.count()).select_from(m.Project))==2

def test_failed_github_sync_preserves_connection_and_projects(db,monkeypatch):
    db.add(m.Integration(provider='github',status='public_inventory',data={'username':'existing'}));db.commit()
    original=httpx.Client
    monkeypatch.setattr(resumes.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(lambda request:httpx.Response(503)),**kwargs))
    with pytest.raises(HTTPException) as error:resumes.github_inventory(db,'fixture')
    assert error.value.status_code==503
    assert db.scalar(select(m.Integration)).data['username']=='existing'

@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DATA_DIR',str(tmp_path));monkeypatch.setenv('PDF_ENGINE','reportlab')
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False) as session:
        session.add(m.ProfileVersion(data={'display_name':'Test-only Applicant','skills':['Python','SQL'],'approved_bullets':['Built a Python project.'],'education':{'degree':'B.Tech','branch':'CSE','university':'Test-only University','graduation_year':2027}}))
        session.add_all([m.Setting(key='ai_enabled',value=False),m.Setting(key='ai_monthly_budget_usd',value=2.5)]);session.commit();yield session
    engine.dispose()

@pytest.fixture
def client(db,monkeypatch):
    import internshipos.api as api
    monkeypatch.setattr(auth,'PASSWORD','');monkeypatch.setattr(api,'PASSWORD','')
    app=FastAPI();app.include_router(public);app.include_router(router)
    app.dependency_overrides[get_db]=lambda:db
    @app.exception_handler(ValueError)
    def error(request,exc):return JSONResponse({'detail':str(exc)},status_code=422)
    with TestClient(app) as test:yield test

def application(db):
    company=m.Company(name='Fixture Labs',domain='example.com',verified=True);db.add(company);db.flush()
    source=m.CompanySource(company_id=company.id,provider='greenhouse',url='https://boards.greenhouse.io/fixture',verified=True);db.add(source);db.commit()
    service.ingest_batch(db,source.id,[{'external_id':'job-1234','title':'Software Engineering Intern','description':'Develop Python software with SQL. Paid internship with engineering mentorship.','location':'Bengaluru, India','apply_url':'https://boards.greenhouse.io/fixture/jobs/job-1234','canonical_url':'https://boards.greenhouse.io/fixture/jobs/job-1234'}],complete=True)
    op=db.scalar(select(m.Opportunity));return service.create_application(db,{'opportunity_id':op.id})

def version(db):
    variant=resumes.create_resume(db,{'name':'Test-only SWE','role_focus':'SWE'})
    return resumes.create_version(db,variant['id'],{'bullets':['Built a Python project.']})

def test_capture_prepare_and_receipt_preserve_submission_truth(client,db):
    assert client.post('/api/capture',json={'url':'https://example.com/jobs/test','title':'Backend Intern','company_name':'Test-only Employer','description':'Build Python services as an intern.','location':'India'}).status_code==201
    op=db.scalar(select(m.Opportunity));assert client.patch('/api/opportunities/'+op.id,json={'saved':True}).json()['saved']
    app=client.post('/api/applications',json={'opportunity_id':op.id}).json();resume=version(db)
    assert client.patch('/api/applications/'+app['id'],json={'resume_version_id':resume['id']}).status_code==200
    pack=client.get('/api/applications/'+app['id']+'/pack').json()
    assert pack['submission_status']=='ready' and pack['resume_version']['id']==resume['id']
    assert client.post('/api/extension/receipt',json={'application_id':app['id'],'url':op.apply_url,'evidence':'Form fields filled'}).status_code==422
    assert db.get(m.Application,app['id']).stage=='ready'
    response=client.post('/api/extension/receipt',json={'application_id':app['id'],'url':op.apply_url,'evidence':'Application received','resume_version_id':resume['id']})
    assert response.status_code==200;assert response.json()['stage']=='applied';assert response.json()['resume_version_id']==resume['id']
    event=db.scalar(select(m.Activity).where(m.Activity.kind=='application.updated').order_by(m.Activity.created_at.desc()))
    assert client.post('/api/activity/'+event.id+'/undo').status_code==200
    assert db.get(m.Application,app['id']).stage=='ready'
    assert db.scalar(select(func.count()).select_from(m.ApplicationEvent))>=3

def test_receipt_cannot_use_other_host_or_regress_interview(client,db):
    app=application(db);service.update_application(db,app['id'],{'stage':'interview'})
    assert client.post('/api/extension/receipt',json={'application_id':app['id'],'url':'https://evil.example/jobs','evidence':'Application received'}).status_code==422
    op=service.get_opportunity(db,app['opportunity_id'])
    assert client.post('/api/extension/receipt',json={'application_id':app['id'],'url':op['apply_url'],'evidence':'Thanks for applying'}).json()['stage']=='interview'

def test_resume_rejects_unapproved_projects_and_fabricated_bullets(db):
    variant=resumes.create_resume(db,{'name':'Test-only SWE'});project=m.Project(name='Unreviewed fixture',approved=False);db.add(project);db.commit()
    for payload in ({'selected_project_ids':[project.id]},{'bullets':['Improved revenue by 90%.']}):
        with pytest.raises(HTTPException) as error:resumes.create_version(db,variant['id'],payload)
        assert error.value.status_code==422

def test_resume_snapshot_does_not_change_with_profile_edit_and_pdf_is_portable(db):
    saved=version(db);obj=db.get(m.ResumeVersion,saved['id']);original=json.dumps(obj.data,sort_keys=True)
    service.save_profile(db,{'display_name':'Different test-only name'})
    assert json.dumps(obj.data,sort_keys=True)==original
    html=resumes.render_html(obj);assert 'Test-only Applicant' in html and 'Test-only University' in html and '&quot;degree&quot;' not in html
    pdf=resumes.pdf_artifact(db,obj);assert pdf.read_bytes().startswith(b'%PDF') and pdf.stat().st_size>1000
    assert resumes.pdf_artifact(db,obj)==pdf

def test_sensitive_profile_fields_and_cross_origin_mutations_are_rejected(client):
    assert client.patch('/api/profile',json={'address':'test'}).status_code==422
    assert client.patch('/api/profile',json={'skills':[]},headers={'Origin':'https://unknown.example'}).status_code==403

def test_owner_and_extension_tokens_have_separate_scopes(client,monkeypatch):
    monkeypatch.setattr(auth,'PASSWORD','test-password')
    assert client.get('/api/settings').status_code==401
    extension=auth.sign_token({'scope':'extension'})
    assert client.get('/api/settings',headers={'Authorization':'Bearer '+extension}).status_code==401
    assert client.get('/api/extension/applications',headers={'Authorization':'Bearer '+extension}).status_code==200
    client.cookies.set(auth.COOKIE,auth.sign_token({'scope':'owner'}));assert client.get('/api/settings').status_code==200
    assert auth.read_token(extension+'x') is None

def test_mail_matching_requires_identity_and_trusted_sender(db):
    app=application(db);op=app['opportunity'];text='Fixture Labs '+op['title']
    assert len(integrations.matching_candidates([app],'Recruiter <hello@example.com>',text,''))==1
    assert integrations.matching_candidates([app],'hello@example.com.evil.test',text,'')==[]
    second={**app,'id':'different-application'}
    assert len(integrations.matching_candidates([app,second],'noreply@greenhouse.io',text,''))==2

def test_email_updates_are_idempotent_reversible_and_do_not_invent_times(db):
    app=application(db);message=m.EmailMessage(provider_message_id='fixture-email',sender='hr@example.com',subject='Interview invitation',body='Interview next Tuesday afternoon',received_at=utcnow(),data={'classification':{'event_type':'interview'}});db.add(message);db.commit()
    result=integrations.apply_email_event(db,message,app['id'],'interview');assert result['stage']=='interview'
    assert integrations.apply_email_event(db,message,app['id'],'interview')['status']=='already_linked'
    task=db.scalar(select(m.Task));assert task.due_at is None and task.date_precision=='unknown'
    audit=db.scalar(select(m.Activity).where(m.Activity.kind=='email_match'));service.undo_activity(db,audit.id)
    assert db.get(m.Application,app['id']).stage=='ready'
    assert db.get(m.Application,app['id']).submitted_at is None
    assert task.completed and task.data['cancelled'] and message.status=='review'
    assert integrations.apply_email_event(db,message,app['id'],'interview',manual=True)['stage']=='interview'
    assert integrations.apply_email_event(db,message,app['id'],'interview')['status']=='already_linked'
    assert integrations.exact_email_time('2026-10-05T14:00:00+05:30').hour==8
    assert integrations.exact_email_time('October 5, 2 PM') is None

def test_older_confirmation_does_not_regress_stage_and_rejection_alias_works(client,db):
    app=application(db);service.update_application(db,app['id'],{'stage':'interview'})
    msg=m.EmailMessage(provider_message_id='older-fixture',subject='Application received',body='received',data={},received_at=utcnow()-timedelta(days=1));db.add(msg);db.commit()
    assert integrations.apply_email_event(db,msg,app['id'],'confirmation')['stage']=='interview'
    msg2=m.EmailMessage(provider_message_id='rejection-fixture',subject='Decision',body='decision',data={});db.add(msg2);db.commit()
    assert client.post('/api/emails/'+msg2.id+'/match',json={'application_id':app['id'],'event_type':'rejected'}).json()['stage']=='rejected'

def test_optional_ai_pauses_without_touching_provider(db,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Provider must not be contacted')
    monkeypatch.setattr(ai,'get_provider',forbidden)
    with pytest.raises(HTTPException) as error:ai.grounded_response(db,'answer',{'facts':[]})
    assert error.value.status_code==409

def test_ai_grounding_cache_and_missing_usage_count_conservatively(db,monkeypatch):
    provider=Provider('openai','gpt-6-luna','test-not-a-real-key','https://example.test',(.1,.5))
    monkeypatch.setattr(ai,'get_provider',lambda strong:provider)
    monkeypatch.setattr(Provider,'generate',lambda *args:({'text':'Built a Python project.','fact_ids':['fact-1'],'unknowns':[]},None,None))
    db.get(m.Setting,'ai_enabled').value=True;db.commit();context={'facts':[{'id':'fact-1','text':'Built a Python project.'}]}
    first=ai.grounded_response(db,'answer',context);assert first['cost']>0 and first['requires_review']
    assert ai.grounded_response(db,'answer',context)['cached']
    monkeypatch.setattr(Provider,'generate',lambda *args:({'text':'Improved revenue by 90%.','fact_ids':['fact-1'],'unknowns':[]},100,100))
    with pytest.raises(HTTPException):ai.grounded_response(db,'answer',{**context,'question':'Different question'})
    assert db.scalar(select(m.AIUsage).where(m.AIUsage.status=='failed')).cost_usd>0
    monkeypatch.setattr(Provider,'generate',lambda *args:({'text':'Built a Rust project.','fact_ids':['fact-1'],'unknowns':[]},100,100))
    with pytest.raises(HTTPException):ai.grounded_response(db,'tailor',context)

def test_ai_zero_budget_blocks_paid_and_local_calls(db):
    db.get(m.Setting,'ai_monthly_budget_usd').value=0;db.commit()
    with pytest.raises(HTTPException) as error:ai.reserve_usage(db,action='test',provider=Provider('local','test','','http://localhost',(0,0)),fingerprint='test',amount=0)
    assert error.value.status_code==402

def test_paid_custom_model_needs_prices(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER','compatible');monkeypatch.setenv('AI_BASE_URL','https://example.test/v1');monkeypatch.setenv('AI_API_KEY','test-only');monkeypatch.setenv('AI_STRONG_MODEL','custom-fixture')
    with pytest.raises(HTTPException) as error:get_provider()
    assert error.value.status_code==409

def test_concurrent_reservations_cannot_exceed_budget(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'budget.db'),connect_args={'check_same_thread':False,'timeout':10});Base.metadata.create_all(engine)
    with Session(engine) as session:session.add(m.Setting(key='ai_monthly_budget_usd',value=.03));session.commit()
    provider=Provider('openai','test-only','','https://example.test',(.1,.5))
    def reserve(index):
        with Session(engine) as session:
            try:ai.reserve_usage(session,action='test',provider=provider,fingerprint=str(index),amount=.02);return True
            except HTTPException as exc:assert exc.status_code==402;return False
    with ThreadPoolExecutor(max_workers=4) as workers:assert sum(workers.map(reserve,range(4)))==1
    with Session(engine) as session:assert ai.budget_status(session)['reserved']==.02
    engine.dispose()

def test_backup_restore_preserves_history_and_excludes_secrets(db,tmp_path):
    app=application(db);service.update_application(db,app['id'],{'stage':'applied'});version(db)
    db.add(m.Integration(provider='google',status='connected',credentials_encrypted='must-never-be-exported',data={'access_token':'also-exclude'}));db.commit()
    path=backup.create_backup(db);assert path.is_file() and backup.backup_status(db)['last_backup_at']
    import zipfile
    with zipfile.ZipFile(path) as archive:
        manifest=archive.read('manifest.json').decode();assert 'must-never-be-exported' not in manifest and 'also-exclude' not in manifest
    other=create_engine('sqlite://');Base.metadata.create_all(other)
    with Session(other) as restored:
        backup.restore_backup(restored,path);assert restored.get(m.Application,app['id']).stage=='applied'
        assert restored.scalar(select(m.Integration)).credentials_encrypted is None
        assert restored.scalar(select(func.count()).select_from(m.ApplicationEvent))>=2
        with pytest.raises(ValueError):backup.restore_backup(restored,path)
    other.dispose()

def test_sources_can_be_paused_and_company_review_requires_evidence(client,db):
    application(db);source=db.scalar(select(m.CompanySource));company=db.get(m.Company,source.company_id)
    assert client.patch('/api/sources/'+source.id,json={'enabled':False,'cadence_hours':36}).json()['enabled'] is False
    assert client.patch('/api/sources/'+source.id,json={'cadence_hours':0}).status_code==422
    assert client.patch('/api/companies/'+company.id,json={'verified':True}).status_code==422
    assert client.patch('/api/companies/'+company.id,json={'verified':True,'verification_url':'https://example.com/about','verification_reason':'Official employer site manually reviewed'}).status_code==200
    source.verified=False;db.commit()
    assert client.patch('/api/sources/'+source.id,json={'verified':True,'verification_url':'https://different.example.org/careers','verification_reason':'The board was reachable'}).status_code==422
    assert client.patch('/api/sources/'+source.id,json={'verified':True,'verification_url':'https://example.com/careers','verification_reason':'Official employer careers page links to this exact board'}).json()['verified'] is True

def test_feed_filters_use_canonical_ids_and_show_trust_separately(client,db):
    app=application(db);op=db.get(m.Opportunity,app['opportunity_id']);op.work_mode='remote';op.compensation={'kind':'employer_stated','min':15000,'currency':'INR','period':'month'};db.commit()
    matched=client.get('/api/opportunities',params={'location':'India','source':'greenhouse','application_stage':'ready','work_mode':'remote','pay':'known','risk':'verified','fresh_days':1}).json()
    assert matched['total']==1 and matched['items'][0]['trust_state']=='verified'
    assert client.get('/api/opportunities?application_stage=none').json()['total']==0
    assert client.get('/api/opportunities?pay=unpaid').json()['total']==0
    source=db.scalar(select(m.CompanySource));source.verified=False;db.commit()
    assert client.get('/api/opportunities?risk=verified').json()['total']==0
    assert client.get('/api/opportunities?risk=no_obvious_concern').json()['items'][0]['trust_state']=='no_obvious_concern'

def test_employer_boilerplate_does_not_make_nontechnical_jobs_technical():
    from internshipos.domain import classify
    for title in ['UX Design - Intern','Game Artist - Internship','3D Artist Intern','Industrial Trainee - Finance & Accounting','Intern - Creative & Communications, People Team','Video Editor Intern']:
        assert classify('Our company uses AI and software for global analytics.',title)['role_family']=='excluded'
    assert classify('Build financial services.','Software Engineer Intern, Finance')['role_family']=='SWE'
    assert classify('','SDE Intern')['role_family']=='SWE'
    assert classify('','SWE Intern')['role_family']=='SWE'
    for title in ['React Native Development - Internship','.NET Development - Internship','Automation Testing - Internship','iOS App Development - Internship']:
        assert classify('Our company uses AI for analytics.',title)['role_family']=='SWE'


def test_personal_location_policy_and_company_priority_are_consistent(db):
    from internshipos.company_priority import install_priorities
    from internshipos.search_policy import location_decision,target_sql
    pairs=[('Bangalore, Karnataka, India','India','onsite','allowed'),('Chennai, India','IN','hybrid','allowed'),('Noida, India','India','onsite','excluded'),('Mumbai, India','India','onsite','excluded'),('Remote, US','US','remote','excluded'),('Remote India','India','remote','allowed'),('India','India','','allowed'),('Remote','','remote','review')]
    for i,(location,country,mode,expected) in enumerate(pairs):
        c=m.Company(name='Unknown Fixture '+str(i),verified=True);db.add(c);db.flush()
        db.add(m.Opportunity(company_id=c.id,title='Software Intern',location=location,country=country,work_mode=mode,role_family='SWE',opportunity_type='internship'))
        assert location_decision(location,country,mode)==expected
    db.commit()
    matched=db.scalars(select(m.Opportunity).where(target_sql(m.Opportunity))).all()
    assert len(matched)==4
    service.save_settings(db,{'personal_location_policy':True})
    assert service.list_opportunities(db,kind='internship')['total']==4
    assert service.analytics(db,scope='india')['summary']['opportunities']==4
    install_priorities(db)
    first=matched[0];first.company.metadata_json={'company_priority':{'score':100,'source':'owner','tier':'Fixture preference'}};first.fit_score=5
    db.commit()
    assert service.list_opportunities(db,sort='company_priority')['items'][0]['id']==first.id


def test_approved_queue_uses_single_lease_and_changed_pack_requires_review(db):
    from internshipos.application_queue import approve,claim
    app=application(db);v=version(db);service.update_application(db,app['id'],{'resume_version_id':v['id']})
    service.save_settings(db,{'auto_apply':{'enabled':True,'providers':['greenhouse'],'daily_limit':1}})
    approve(db,app['id'],True)
    profile=service.get_profile(db);service.save_profile(db,{**profile,'skills':['Python','SQL','Java']})
    with pytest.raises(ValueError,match='changed'):claim(db,app['id'])
    approve(db,app['id'],True);lease=claim(db,app['id'])
    assert lease['resume_version_id']==v['id']
    with pytest.raises(ValueError,match='already has'):claim(db,app['id'])
    assert db.get(m.Application,app['id']).stage=='ready'


def test_queue_daily_limit_counts_uncertain_and_reserved_attempts(db):
    from internshipos.application_queue import approve,claim
    app=application(db);v=version(db);service.update_application(db,app['id'],{'resume_version_id':v['id']})
    service.save_settings(db,{'auto_apply':{'enabled':True,'providers':['greenhouse'],'daily_limit':1}})
    approve(db,app['id'],True)
    db.add(m.Activity(kind='submission_reserved',title='Earlier uncertain attempt'));db.commit()
    with pytest.raises(ValueError,match='Daily'):claim(db,app['id'])
    assert db.get(m.Application,app['id']).data['auto_apply']['state']=='approved'


def test_uncertain_queue_attempt_cannot_retry_but_can_record_late_receipt(client,db):
    from internshipos.application_queue import approve,claim,stop
    app=application(db);v=version(db);service.update_application(db,app['id'],{'resume_version_id':v['id']})
    service.save_settings(db,{'auto_apply':{'enabled':True,'providers':['greenhouse'],'daily_limit':2}})
    approve(db,app['id'],True);lease=claim(db,app['id']);stop(db,app['id'],'uncertain')
    with pytest.raises(ValueError,match='already has'):claim(db,app['id'])
    op=db.get(m.Opportunity,app['opportunity_id'])
    payload={'application_id':app['id'],'url':op.apply_url,'evidence':'Application received','resume_version_id':v['id'],'lease':'incorrect'}
    assert client.post('/api/extension/receipt',json=payload).status_code==422
    payload['lease']=lease['lease']
    assert client.post('/api/extension/receipt',json=payload).status_code==200
    assert db.get(m.Application,app['id']).data['auto_apply']['state']=='submitted'


def test_detail_budget_is_partial_and_never_proves_closure(db):
    app=application(db);op=db.get(m.Opportunity,app['opportunity']['id']);source=db.scalar(select(m.CompanySource))
    outcome=service.ingest_batch(db,source.id,[],complete=True,error='detail_limit_reached')
    assert outcome['status']=='partial' and not outcome['complete']
    assert op.status=='active'
    from internshipos.source_health import health
    assert health(source)['label']=='Partial'


def test_target_storage_filter_preserves_raw_inventory_without_false_quarantine(db):
    app=application(db);source=db.scalar(select(m.CompanySource));op=db.get(m.Opportunity,app['opportunity']['id'])
    record={'external_id':'job-1234','title':op.title,'description':op.description,'location':op.location,'canonical_url':op.canonical_url,'apply_url':op.apply_url}
    outcome=service.ingest_batch(db,source.id,[record],complete=True,observed_count=2,inventory_ids=['job-1234','foreign-new-role'])
    assert outcome['status']=='complete' and op.status=='active'
    unsafe=service.ingest_batch(db,source.id,[],complete=True,observed_count=1,inventory_ids=['job-1234'])
    assert unsafe['status']=='quarantined' and op.status=='active'
