import asyncio
import json

import httpx
import pytest

from internshipos.ingestion import collect_source
from internshipos.ingestion.public_pages import assigned_json, kula_records
from internshipos.ingestion.types import SchemaError


def collect(url, handler, config=None, **options):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect_source({'provider': 'generic', 'url': url, 'company_name': 'Acme',
                                         'config': config or {}}, client=client, resolve_dns=False, **options)
    return asyncio.run(run())


def router(data):
    return '<script>window.__staticRouterHydrationData = JSON.parse(' + json.dumps(json.dumps(data)) + ');</script>'


def apple_row(i):
    return {'id': 'R'+str(i), 'positionId': str(i), 'reqId': 'R'+str(i),
            'postingTitle': 'Software Intern', 'transformedPostingTitle': 'software-intern',
            'locations': [{'city': 'Bengaluru', 'country': 'India'}], 'jobSummary': 'summary only'}


def test_apple_native_paging_preserves_region_and_enriches_only_full_detail():
    calls = []
    def handler(request):
        calls.append(request)
        if '/details/' in request.url.path:
            ident = request.url.path.split('/')[3]
            return httpx.Response(200, text=router({'loaderData': {'details': {
                'positionId': ident, 'description': 'Full description', 'responsibilities': 'Build APIs'}}}))
        page = int(request.url.params['page'])
        assert request.url.params['location'] == 'india-INDC'
        rows = [apple_row(i) for i in range((page-1)*20, min(21,page*20))]
        return httpx.Response(200, text=router({'loaderData': {'search': {'searchResults': rows, 'totalRecords': 21}}}))
    result = collect('https://jobs.apple.com/en-us/search?location=india-INDC', handler,
                     {'source': 'reactrouter'}, max_details=1)
    assert len(result.jobs) == 21 and result.metadata['inventory_complete']
    assert result.coverage_scope == 'query' and not result.complete
    assert result.jobs[0]['description'] == 'Full description\n\nBuild APIs'
    assert not result.jobs[1]['description']
    assert result.metadata['next_detail_cursor'] == 1
    assert 'detail_limit_reached' in result.error


def test_apple_repeated_page_cannot_prove_inventory():
    def handler(r):
        return httpx.Response(200, text=router({'loaderData': {'search': {'searchResults': [apple_row(1)]*20, 'totalRecords': 21}}}))
    result = collect('https://jobs.apple.com/en-us/search', handler, {'source': 'reactrouter'}, max_details=0)
    assert not result.complete and not result.metadata['inventory_complete']
    assert 'pagination_repeated_page' in result.error


@pytest.mark.parametrize('identity,accepted', [({'jobNumber': '1'}, True),
    ({'positionId': '1', 'jobNumber': 'OTHER'}, False), ({}, False)])
def test_apple_actual_job_details_loader_binds_full_sections_to_native_identity(identity, accepted):
    def handler(request):
        if '/details/' in request.url.path:
            return httpx.Response(200, text=router({'loaderData': {'jobDetails': {'jobsData': {
                **identity, 'jobSummary': 'Employer summary', 'description': 'Full description',
                'responsibilities': 'Build APIs', 'minimumQualifications': 'Python required'}}}}))
        return httpx.Response(200, text=router({'loaderData': {'search': {
            'searchResults': [apple_row(1)], 'totalRecords': 1}}}))
    result = collect('https://jobs.apple.com/en-us/search', handler, {'source': 'reactrouter'})
    if accepted:
        assert result.complete
        assert result.jobs[0]['description'] == 'Employer summary\n\nFull description\n\nBuild APIs\n\nPython required'
    else:
        assert not result.complete and not result.jobs[0]['description']
        assert 'apple_detail_identity_mismatch' in result.error


def test_apple_detail_identity_mismatch_does_not_copy_recommended_role():
    def handler(r):
        data = {'details': {'positionId': 'OTHER', 'description': 'Wrong full detail'}} if '/details/' in r.url.path else {
            'search': {'searchResults': [apple_row(1)], 'totalRecords': 1}}
        return httpx.Response(200, text=router({'loaderData': data}))
    result = collect('https://jobs.apple.com/en-us/search', handler, {'source': 'reactrouter'})
    assert not result.complete and not result.jobs[0]['description']
    assert 'apple_detail_identity_mismatch' in result.error


@pytest.mark.parametrize('expression', ['fetch("https://evil.example")', '{"a":1}.constructor', 'JSON.parse(fetch("x"))'])
def test_json_state_does_not_execute_javascript(expression):
    with pytest.raises(SchemaError):
        assigned_json('<script>window.jobsList = '+expression+';</script>', 'window.jobsList')


def kula_html(rows, text='Build Python APIs café'):
    flight = '24:T'+format(len(text.encode('utf-8')), 'x')+','+text+'25:T3,End\n1:'+json.dumps({'jobs': rows})
    script = '<script>self.__next_f.push('+json.dumps([1, flight])+')</script>'
    return script + ''.join('<a href="/acme/'+str(x['id'])+'-software-intern">Apply Now</a>' for x in rows)


def kula_row():
    return {'id': 123, 'title': 'Software Intern', 'listed': True, 'kind': 'internal_and_external',
            'is_confidential': False, 'ats_job': {'job_description': '$24', 'workplace': 'office',
            'work_type_name': 'Internship', 'offices': [{'location': 'Bengaluru, India'}]}}


def test_kula_utf8_length_references_and_adjacent_records_preserve_full_jd():
    html = kula_html([kula_row()])
    rows, texts = kula_records(html)
    assert texts['24'] == 'Build Python APIs café' and texts['25'] == 'End'
    result = collect('https://careers.kula.ai/acme', lambda r: httpx.Response(200, text=html))
    assert result.complete and result.coverage_scope == 'discovery'
    assert result.jobs[0]['description'] == 'Build Python APIs café'
    assert result.jobs[0]['canonical_url'] == 'https://careers.kula.ai/acme/123-software-intern'


@pytest.mark.parametrize('change', [{'listed': False}, {'is_confidential': True}, {'kind': 'internal'}])
def test_kula_unlisted_confidential_internal_roles_not_ingested(change):
    row = {**kula_row(), **change}
    result = collect('https://careers.kula.ai/acme', lambda r: httpx.Response(200, text=kula_html([row])))
    assert not result.jobs


def test_kula_missing_native_link_does_not_invent_application_url():
    html = kula_html([kula_row()]).split('<a')[0]
    result = collect('https://careers.kula.ai/acme', lambda r: httpx.Response(200, text=html))
    assert not result.complete and 'kula_native_job_url_missing' in result.error


def test_recruiterflow_group_native_identifiers_are_not_department_names():
    rows = [{'job_id': 123, 'job_name': 'Software Intern', 'apply_link': 'acme/jobs/123',
             'details': 'Bengaluru, India', 'employment_type': 'Internship'}]
    html = '<script>window.jobsList = '+json.dumps({'group': [['Engineering', rows]]})+';</script>'
    def handler(request):
        if request.url.path.endswith('/123'):
            return httpx.Response(200, text='<div class="job-description">Build Python APIs</div>')
        return httpx.Response(200, text=html)
    result = collect('https://recruiterflow.com/acme/jobs', handler)
    assert result.complete and result.jobs[0]['external_id'] == '123'
    assert result.jobs[0]['canonical_url'] == 'https://recruiterflow.com/acme/jobs/123'
    assert result.jobs[0]['description'] == 'Build Python APIs'


def google_card(ident='123', title='Software Intern'):
    return '<li class="lLd3Je"><h3 class="QJPWVe">'+title+'</h3><span class="r0wTof">Bengaluru, India</span><a href="jobs/results/'+ident+'-software-intern">More</a></li>'


def google_detail(ident='123', title='Software Intern'):
    return '<div class="DkhPwc" data-id="'+ident+'"><h2 class="p1N2lc">'+title+'</h2><div><h3>About the job</h3>Build APIs</div><div><h3>Responsibilities</h3>Test Python</div></div>'


def test_google_document_base_full_pane_and_native_identity():
    calls = []
    def handler(r):
        calls.append(str(r.url))
        text = google_detail()+'<div><h3>About the job</h3>Unrelated recommended role</div>' if '/123-' in r.url.path else (
            '<base href="https://www.google.com/about/careers/applications/">'+google_card())
        return httpx.Response(200, text=text)
    result = collect('https://www.google.com/about/careers/applications/jobs/results/', handler)
    assert result.complete and result.coverage_scope == 'query'
    assert result.jobs[0]['external_id'] == '123'
    assert 'Unrelated' not in result.jobs[0]['description'] and 'Build APIs' in result.jobs[0]['description']
    assert '/jobs/results/jobs/results/' not in calls[-1]


@pytest.mark.parametrize('ident,title', [('OTHER','Software Intern'), ('123','Different title')])
def test_google_active_pane_mismatch_keeps_jd_unconfirmed(ident,title):
    def handler(r):
        return httpx.Response(200,text=google_detail(ident,title) if '/123-' in r.url.path else (
            '<base href="https://www.google.com/about/careers/applications/">'+google_card()))
    result = collect('https://www.google.com/about/careers/applications/jobs/results/', handler)
    assert not result.complete and not result.jobs[0]['description']
    assert 'google_detail_identity_mismatch' in result.error


def test_declared_public_feed_excludes_closed_records_without_inventing_zero_failure():
    config = {'api_url': 'https://public.example/jobs', 'json_path': 'allJobs',
              'record_filter': {'opening_status': True},
              'fields': {'id': 'job_id', 'title': 'job_title', 'description': 'job_description'},
              'url_template': 'https://public.example/jobs/{job_id}'}
    row = {'job_id': 'J1', 'job_title': 'Software Intern', 'job_description': 'Build APIs', 'opening_status': False}
    result = collect('https://public.example/careers', lambda r: httpx.Response(200,json={'allJobs':[row]}),config)
    assert result.complete and not result.jobs
    result = collect('https://public.example/careers', lambda r: httpx.Response(200,json={'allJobs':[{**row,'opening_status':True}]}),config)
    assert result.complete and result.jobs[0]['external_id'] == 'J1'
