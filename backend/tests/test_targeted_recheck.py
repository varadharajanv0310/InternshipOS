"""A role recheck resolves stored identities and never refreshes a board clock."""
import asyncio
from datetime import datetime,timedelta,timezone

import httpx
import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker

from internshipos import jobs,service
from internshipos.db import Base,aware
from internshipos.ingestion import collect_source,CollectionResult
from internshipos.models import Company,CompanySource,Opportunity,JobSource,FetchRun

NOW=datetime(2026,10,8,8,tzinfo=timezone.utc)
URL='https://boards.greenhouse.io/acme/jobs/123'


def collect(provider,payload,*,url='https://boards.greenhouse.io/acme',target=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload))) as client:
            return await collect_source({'provider':provider,'url':url,'config':{
                'refresh_jobs':[target or {'external_id':'123','canonical_url':URL,'company_name':'Acme'}]}},
                client=client,resolve_dns=False)
    return asyncio.run(run())


def test_greenhouse_native_id_is_checked_independently_of_requisition_id():
    result=collect('greenhouse',{'id':123,'requisition_id':'REQ-OTHER','title':'Software Intern',
        'content':'Full internship requirements','absolute_url':URL},
        target={'external_id':'123','requisition_id':'REQ-OTHER','canonical_url':URL})
    assert result.complete and result.coverage_scope=='targeted'
    assert result.jobs[0]['external_id']=='123' and result.jobs[0]['requisition_id']=='REQ-OTHER'


@pytest.mark.parametrize('payload,reason',[
    ({'id':456,'title':'Different intern','content':'Other role','absolute_url':URL},'native_identity_mismatch'),
    ({'id':123,'title':'Software Intern','content':'Full requirements','absolute_url':'https://other-employer.test/job/123'},'url_host_mismatch'),
])
def test_greenhouse_wrong_native_identity_or_employer_url_stays_uncertain(payload,reason):
    result=collect('greenhouse',payload)
    assert not result.complete and not result.jobs and reason in result.error


@pytest.mark.parametrize('external_id,req,expected',[
    ('JR123','JR123',True),('/job/India/Software-Intern_JR123','JR123',True),
    ('India','JR123',False),('JR123','JR999',False),
])
def test_workday_path_identity_handles_native_and_path_ids_but_rejects_location_ids(external_id,req,expected):
    result=collect('workday',{'jobPostingInfo':{'title':'Software Intern','jobDescription':'Full requirements',
        'jobReqId':req,'location':'India'}},url='https://acme.wd1.myworkdayjobs.com/External',
        target={'external_id':external_id,'canonical_url':'https://acme.wd1.myworkdayjobs.com/External/job/India/Software-Intern_JR123'})
    assert result.complete is expected
    assert bool(result.jobs) is expected
    if not expected:assert 'native_identity_mismatch' in result.error


def test_jsonld_recheck_cannot_rebind_another_role_or_employer():
    import json
    async def run(native,url,employer):
        data={'@type':'JobPosting','identifier':native,'url':url,'title':'Software Intern',
            'description':'Full requirements','hiringOrganization':{'name':employer}}
        html='<script type="application/ld+json">'+json.dumps(data)+'</script>'
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,text=html))) as client:
            return await collect_source({'provider':'generic','url':'https://careers.acme.test',
                'config':{'refresh_jobs':[{'external_id':'123','canonical_url':'https://careers.acme.test/jobs/123','company_name':'Acme'}]}},
                client=client,resolve_dns=False)
    for native,url,employer in [('999','https://careers.acme.test/jobs/999','Acme'),
                               ('999','https://careers.acme.test/jobs/123','Acme'),
                               ('123','https://careers.acme.test/jobs/123','Other employer')]:
        result=asyncio.run(run(native,url,employer))
        assert not result.jobs
        assert 'identity_mismatch' in result.error or 'employer_mismatch' in result.error


def test_jsonld_redirect_cannot_inherit_the_requested_url_as_identity():
    async def run():
        def handler(request):
            if request.url.path=='/jobs/123':return httpx.Response(302,headers={'Location':'/jobs/999'})
            return httpx.Response(200,text='<script type="application/ld+json">{"@type":"JobPosting","title":"Different role","description":"Full other role","hiringOrganization":{"name":"Acme"}}</script>')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect_source({'provider':'generic','url':'https://careers.acme.test',
                'config':{'refresh_jobs':[{'external_id':'123','canonical_url':'https://careers.acme.test/jobs/123','company_name':'Acme'}]}},
                client=client,resolve_dns=False)
    result=asyncio.run(run())
    assert not result.jobs and 'redirect_identity_mismatch' in result.error


@pytest.fixture
def stored(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'recheck.db'),connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine,expire_on_commit=False)
    monkeypatch.setattr(jobs,'SessionLocal',factory)
    with factory() as db:
        company=Company(name='Acme',domain='acme.test',verified=True);other=Company(name='Other');db.add_all([company,other]);db.flush()
        old=NOW-timedelta(days=3)
        source=CompanySource(company_id=company.id,provider='greenhouse',url='https://boards.greenhouse.io/acme',
            enabled=True,verified=True,status='complete',last_checked=old,last_success=old,
            config={'board_checked_at':old.isoformat(),'detail_cursor':9,'listing_cursor':4,'retained_detail_cursor':2})
        unverified=CompanySource(company_id=company.id,provider='greenhouse',url='https://boards.greenhouse.io/candidate',enabled=True,verified=False)
        foreign=CompanySource(company_id=other.id,provider='greenhouse',url='https://boards.greenhouse.io/other',enabled=True,verified=True)
        db.add_all([source,unverified,foreign]);db.flush()
        op=Opportunity(company_id=company.id,title='Software Intern',description='Older full requirements',
            canonical_url=URL,apply_url=URL,status='active',location='Bengaluru, India',data={})
        db.add(op);db.flush()
        rows=[JobSource(company_source_id=s.id,opportunity_id=op.id,external_id='123',url=URL,last_seen=old,last_detail_checked=old)
            for s in (source,unverified,foreign)]
        db.add_all(rows);db.commit()
        ids=(op.id,source.id,rows[0].id,old)
    yield factory,ids
    engine.dispose()


@pytest.mark.parametrize('success',[True,False])
def test_manual_role_recheck_resolves_verified_employer_and_preserves_inventory_clocks(stored,monkeypatch,success):
    factory,(opid,sourceid,appearanceid,old)=stored;seen=[]
    async def collect(source,**kwargs):
        seen.append(source)
        return CollectionResult(jobs=[{'external_id':'123','title':'Software Intern','description':'Updated full requirements',
            'canonical_url':URL,'apply_url':URL,'company_name':'Acme','location':'Bengaluru, India'}] if success else [],
            complete=success,error=None if success else 'HTTP 404',coverage_scope='targeted')
    monkeypatch.setattr('internshipos.ingestion.collect_source',collect)
    result=asyncio.run(jobs.refresh_opportunity(opid))
    assert result['sources']==1 and seen[0]['id']==sourceid and result['worker_errors']==0
    assert seen[0]['config']['refresh_jobs'][0]['opportunity_id']==opid
    with factory() as db:
        source=db.get(CompanySource,sourceid);appearance=db.get(JobSource,appearanceid);op=db.get(Opportunity,opid)
        assert source.config['board_checked_at']==old.isoformat()
        assert source.config['detail_cursor']==9 and source.config['listing_cursor']==4 and source.config['retained_detail_cursor']==2
        assert op.status!='confirmed_closed'
        if success:assert aware(appearance.last_detail_checked)>old and op.description=='Updated full requirements'
        else:assert aware(appearance.last_detail_checked)==old and aware(appearance.last_seen)==old
        assert db.scalar(select(FetchRun)).coverage_scope=='targeted'


def test_recheck_dedupes_the_same_role_without_conflating_distinct_roles(stored):
    factory,(opid,*_)=stored
    with factory() as db:
        one=jobs.enqueue(db,'refresh_opportunity',{'opportunity_id':opid})
        same=jobs.enqueue(db,'refresh_opportunity',{'opportunity_id':opid})
        other=jobs.enqueue(db,'refresh_opportunity',{'opportunity_id':'another-role'})
        assert one['job_id']==same['job_id'] and same['already_queued'] is True
        assert other['job_id']!=one['job_id']
