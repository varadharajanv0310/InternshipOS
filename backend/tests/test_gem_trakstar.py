import asyncio
import httpx
import pytest
from internshipos.ingestion import collect_source

def collect(url, handler, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect_source({'provider':'generic','url':url,'company_name':'Acme'},
                                        client=client, resolve_dns=False, **kwargs)
    return asyncio.run(run())

def row(**extra):
    return {'id':'native-123','title':'Software Intern','absolute_url':'https://jobs.gem.com/acme/native-123',
            'content':'<p>Build Python APIs</p>','location':{'name':'Bengaluru, India'},
            'requisition_id':'R5','first_published_at':'2026-10-08T01:00:00Z', **extra}

def test_gem_inline_full_inventory_uses_native_ids_and_no_detail_budget():
    calls=[]
    def handler(r):
        calls.append(str(r.url)); return httpx.Response(200,json=[row()])
    result=collect('https://jobs.gem.com/acme',handler,max_details=0)
    assert calls==['https://api.gem.com/job_board/v0/acme/job_posts/']
    assert result.complete and result.coverage_scope=='full'
    assert result.jobs[0]['description']=='Build Python APIs'
    assert result.jobs[0]['external_id']=='native-123' and result.jobs[0]['requisition_id']=='R5'

@pytest.mark.parametrize('rows,error', [([row(absolute_url='https://jobs.gem.com/other/native-123')],'identity_mismatch'),
    ([row(),row()],'duplicate_listing'),([row(content='')],'full_description_unavailable'),({'jobs':[]},'array_missing')])
def test_gem_schema_identity_or_missing_content_cannot_be_full_success(rows,error):
    result=collect('https://jobs.gem.com/acme',lambda r:httpx.Response(200,json=rows))
    assert not result.complete and error in result.error

def page():
    return '<div class="js-openings-list"><div class="js-careers-page-job-list-item" data-href="/jobs/fk123/"><h3 class="js-job-list-opening-name">Software Intern</h3><div class="js-job-list-opening-loc" title="Chennai, India"></div></div></div>'

def test_trakstar_reads_only_bound_jd_and_keeps_discovery_scope():
    def handler(r):
        return httpx.Response(200,text=page() if r.url.path=='/' else '<div class="js-job-title">Software Intern</div><div class="jobdesciption">Build APIs</div><form>Unrelated application questions</form>')
    result=collect('https://acme.hire.trakstar.com/',handler)
    assert result.complete and result.coverage_scope=='discovery'
    assert result.jobs[0]['description']=='Build APIs' and result.jobs[0]['location']=='Chennai, India'

def test_trakstar_wrong_role_or_exhausted_budget_never_promotes_description():
    handler=lambda r:httpx.Response(200,text=page() if r.url.path=='/' else '<div class="js-job-title">Other Job</div><div class="jobdesciption">Wrong description</div>')
    result=collect('https://acme.hire.trakstar.com/',handler)
    assert not result.complete and not result.jobs[0]['description'] and 'identity_mismatch' in result.error
    result=collect('https://acme.hire.trakstar.com/',handler,max_details=0)
    assert not result.complete and 'detail_limit_reached' in result.error

def test_trakstar_error_page_is_not_empty_success():
    result=collect('https://acme.hire.trakstar.com/',lambda r:httpx.Response(200,text='<h1>Service unavailable</h1>'))
    assert not result.complete and 'native_openings_missing' in result.error
