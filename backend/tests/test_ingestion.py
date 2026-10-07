import asyncio
import gzip
import json
from pathlib import Path

import httpx
import pytest

from internshipos.ingestion import Source, collect_source, discover_company
from internshipos.ingestion.adapters import workday_target
from internshipos.ingestion.discovery import parse_unstop
from internshipos.ingestion.http import SourceError, validate_public_url
from internshipos.ingestion.parsing import parse_jsonld, safe_html
from internshipos.ingestion.registry import default_discovery_sources, import_openjobs

FIXTURES = Path(__file__).parents[1] / "internshipos/ingestion/fixtures"


def test_internshala_cards_preserve_employer_and_internship_context():
    from internshipos.search_policy import retain_new_candidate
    html='''<div class="individual_internship"><a class="job-title" href="/internship/detail/software-development-internship-in-chennai-at-acme123">Software Development</a><p class="company-name">Acme</p></div><div class="individual_internship"><a class="job-title" href="/internship/detail/data-science-work-from-home-internship-at-beta456">Data Science</a><p class="company-name">Beta</p></div>'''
    result=collect('internshala',lambda r:httpx.Response(200,text=html),url='https://internshala.com/internships/software-development-internship-in-chennai/',max_details=0)
    assert result.complete and result.coverage_scope=='discovery'
    assert result.metadata['description_scope']=='listing_only' and not result.metadata['description_complete']
    assert [j['company_name'] for j in result.jobs]==['Acme','Beta']
    assert all(j['description']=='' and retain_new_candidate(j) for j in result.jobs)
    empty=collect('internshala',lambda r:httpx.Response(200,text='<h1>Access unavailable</h1>'))
    assert not empty.complete and 'no_recognized_cards' in empty.error


def test_workday_budget_rotates_details_without_losing_listing_inventory():
    def handler(request):
        if request.method=='POST':
            return httpx.Response(200,json={'total':3,'jobPostings':[{'externalPath':'/job/Chennai/Software-Intern_R'+str(i),'title':'Software Intern','bulletFields':['R'+str(i)]} for i in range(3)]})
        ident=request.url.path.rsplit('_',1)[-1]
        return httpx.Response(200,json={'jobPostingInfo':{'jobReqId':ident,'title':'Software Intern','location':'Chennai','jobDescription':'Build Python software.'}})
    url='https://fixture.wd1.myworkdayjobs.com/Careers'
    first=collect('workday',handler,url=url,max_details=1)
    assert not first.complete and len(first.jobs)==3 and first.metadata['inventory_complete'] and first.metadata['next_detail_cursor']==1
    assert [x['external_id'] for x in first.jobs if x['description']]==['R0']
    second=collect('workday',handler,url=url,max_details=1,config={'detail_cursor':1})
    assert [x['external_id'] for x in second.jobs if x['description']]==['R1']
    assert second.coverage_scope=='full' and second.metadata['next_detail_cursor']==2 and second.metadata['inventory_complete']
    last=collect('workday',handler,url=url,max_details=1,config={'detail_cursor':2})
    assert [x['external_id'] for x in last.jobs if x['description']]==['R2']
    assert last.coverage_scope=='full' and last.metadata['next_detail_cursor']==0 and last.metadata['inventory_complete']


def test_declared_public_json_feed_preserves_fields_and_checks_schema():
    config={'api_url':'https://feed.example.com/jobs.json','json_path':'Report_Entry','fields':{'title':'Title','description':'Description','locations':'Location','metadata.ats_job_id':'Req'},'url_template':'https://jobs.example.com/job/{Req}/{slug}/','slug_fields':['Title']}
    result=collect('generic',lambda r:httpx.Response(200,json={'Report_Entry':[{'Req':'42','Title':'Software Intern','Description':'Build Python APIs','Location':'Chennai'}]}),config=config)
    assert result.complete and result.coverage_scope=='discovery'
    assert result.jobs[0]['external_id']=='42' and result.jobs[0]['description']=='Build Python APIs'
    assert result.jobs[0]['apply_url']=='https://jobs.example.com/job/42/software-intern/'
    invalid=collect('generic',lambda r:httpx.Response(200,json={'Error':'schema drift'}),config=config)
    assert not invalid.complete and 'expected_array' in invalid.error


def collect(provider, handler, url=None, config=None, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect_source({"provider": provider, "url": url or "https://jobs.example.com/acme",
                "config": config or {}, "company_name": "Acme", "company_domain": "acme.example.com"},
                client=client, resolve_dns=False, **kwargs)
    return asyncio.run(run())


def test_greenhouse_complete_and_empty_are_explicit_schemas():
    payload = {"jobs": [{"id": 12, "title": "Software Intern", "content": "<p>Build Python APIs</p>",
        "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/12", "location": {"name": "Bengaluru"},
        "requisition_id": "REQ-12"}], "meta": {"total": 1}}
    result = collect("greenhouse", lambda r: httpx.Response(200, json=payload))
    assert result.complete and result.coverage_scope == "full"
    assert result.jobs[0]["description"] == "Build Python APIs"
    assert result.jobs[0]["external_id"] == "12"
    assert result.jobs[0]["requisition_id"] == "REQ-12"
    empty = collect("greenhouse", lambda r: httpx.Response(200, json={"jobs": [], "meta": {"total": 0}}))
    assert empty.complete and empty.observed_count == 0
    changed = collect("greenhouse", lambda r: httpx.Response(200, json={"error": "upstream changed"}))
    assert not changed.complete and "expected_array" in changed.error


def test_tracker_leads_keep_employer_identity_and_do_not_invent_descriptions():
    markdown='| Company | Position | Location | Apply | Age |\n| --- | --- | --- | --- | --- |\n| <b>Acme</b> | Software Intern | Chennai, India | <a href="https://jobs.example.com/123">Apply</a> | 2d |\n| ↳ | ML Intern | Bengaluru, India | [Apply](https://jobs.example.com/456) | 3d |'
    result=collect('github_tracker',lambda r:httpx.Response(200,text=markdown))
    assert result.complete and result.coverage_scope=='discovery'
    assert len(result.jobs)==2
    assert all(j['company_name']=='Acme' and j['description']=='' and j['posted_at'] is None for j in result.jobs)
    assert result.jobs[0]['evidence'][0]['age_raw']=='2d'


def test_search_targets_include_multiple_queries_and_tracker_category_paths():
    sources=default_discovery_sources()
    assert len({s['config'].get('search_term') for s in sources if s['provider']=='linkedin'})>=10
    assert any(s['provider']=='github_tracker' for s in sources)
    assert any('internship-in-chennai' in s['url'] for s in sources)
    assert any('work-from-home' in s['url'] for s in sources)


def test_hosted_retention_keeps_relevant_india_and_uncertain_remote_leads():
    from internshipos.search_policy import retain_new_candidate
    base={'title':'Software Engineer Intern','description':'Build Python APIs','location':'Chennai, India'}
    assert retain_new_candidate(base)
    assert retain_new_candidate({**base,'location':'Remote'})
    assert not retain_new_candidate({**base,'location':'San Francisco, CA'})
    assert not retain_new_candidate({**base,'location':'Remote','country':'US'})
    assert not retain_new_candidate({**base,'title':'WordPress Developer Intern'})
    assert not retain_new_candidate({**base,'title':'Sales Intern'})


def test_challenge_is_not_successful_zero():
    result = collect("greenhouse", lambda r: httpx.Response(406, text="recaptcha required"))
    assert not result.complete and result.jobs == []
    assert "challenged" in result.error


def test_compressed_public_json_is_decoded_exactly_once():
    data = gzip.compress(json.dumps({"jobs": [], "meta": {"total": 0}}).encode())
    result = collect("greenhouse", lambda r: httpx.Response(200, headers={"content-encoding": "gzip"}, content=data))
    assert result.complete and result.error is None


def test_job_limit_keeps_partial_records():
    records = [{"id": i, "title": f"Intern {i}", "content": "Python", "absolute_url": f"https://example.com/{i}"} for i in range(3)]
    result = collect("greenhouse", lambda r: httpx.Response(200, json={"jobs": records}), max_jobs=2)
    assert len(result.jobs) == 2 and not result.complete and "job_limit" in result.error


@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://169.254.169.254/latest/meta-data", "http://10.0.0.1",
    "http://localhost", "file:///etc/passwd", "https://user:pass@example.com/", "http://example.com:8080/", "http://[::1]/"])
def test_private_and_unsafe_targets_rejected(url):
    with pytest.raises(SourceError):
        asyncio.run(validate_public_url(url, resolve_dns=False))


def test_public_host_resolving_private_rejected(monkeypatch):
    async def run():
        async def fake(*args, **kwargs):
            return [(2, 1, 6, "", ("192.168.1.3", 443))]
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake)
        with pytest.raises(SourceError):
            await validate_public_url("https://jobs.example.com")
    asyncio.run(run())


def test_redirect_private_destination_never_requested():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
    result = collect("greenhouse", handler)
    assert not result.complete and len(calls) == 1 and "unsafe" in result.error


def test_workday_locale_and_high_numbered_host():
    s = Source("workday", "https://acme.wd103.myworkdayjobs.com/en-US/External/job/test")
    assert workday_target(s) == ("https://acme.wd103.myworkdayjobs.com", "acme", "External")
    s = Source("workday", "https://wd3.myworkdaysite.com/recruiting/acme/External")
    assert workday_target(s)[1:] == ("acme", "External")
    s = Source.from_value({"provider": "workday", "url": "https://acme.wd5.myworkdayjobs.com/External", "board": "acme-careers-registry-label"})
    assert workday_target(s)[2] == "External"


def test_workday_full_details_and_filtered_scope():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.method == "POST":
            assert json.loads(request.content)["limit"] == 20
            return httpx.Response(200, json={"total": 1, "jobPostings": [{"title": "Software Intern", "externalPath": "/job/India/Intern_JR1", "bulletFields": ["JR1"]}]})
        return httpx.Response(200, json={"jobPostingInfo": {"title": "Software Intern", "jobReqId": "JR1", "jobDescription": "<p>Python and SQL</p>", "location": "Chennai", "startDate": "2026-10-01", "endDate": "2026-10-30"}})
    result = collect("workday", handler, "https://acme.wd103.myworkdayjobs.com/en-US/External", config={"search_text": "intern"})
    assert result.complete and result.coverage_scope == "query"
    assert result.jobs[0]["description"] == "Python and SQL"
    assert result.jobs[0]["canonical_url"] == "https://acme.wd103.myworkdayjobs.com/External/job/India/Intern_JR1"
    assert paths[0] == "/wday/cxs/acme/External/jobs"


def test_workday_cap_cannot_report_complete():
    def handler(request):
        return httpx.Response(200, json={"total": 2000, "jobPostings": [{"title": "Intern", "externalPath": "/job/1", "bulletFields": ["1"]}]})
    result = collect("workday", handler, "https://acme.wd1.myworkdayjobs.com/External", max_pages=1, max_details=0)
    assert not result.complete and len(result.jobs) == 1 and "cap" in result.error


def test_workday_discovers_country_and_early_career_facets():
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(200, json={"total": 5000, "jobPostings": [], "facets": [
                {"facetParameter": "locationMainGroup", "values": [{"facetParameter": "locationHierarchy1", "values": [{"id": "INDIA_ID", "descriptor": "India"}]}]},
                {"facetParameter": "workerSubType", "values": [{"id": "INTERN", "descriptor": "Intern (Fixed Term)"}, {"id": "GRAD", "descriptor": "New College Graduate"}, {"id": "OTHER", "descriptor": "Regular Employee"}]}]})
        return httpx.Response(200, json={"total": 0, "jobPostings": []})
    result = collect("workday", handler, "https://acme.wd1.myworkdayjobs.com/External", config={"search_text": "intern", "country_name": "India", "early_career": True})
    assert result.complete and result.coverage_scope == "query"
    assert calls[1]["appliedFacets"] == {"locationHierarchy1": ["INDIA_ID"], "workerSubType": ["INTERN", "GRAD"]}
    assert calls[1]["searchText"] == ""


def test_detail_failure_preserves_listing_but_not_full_health():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"total": 1, "jobPostings": [{"title": "Intern", "externalPath": "/job/1", "bulletFields": ["1"]}]})
        return httpx.Response(404)
    result = collect("workday", handler, "https://acme.wd1.myworkdayjobs.com/External")
    assert len(result.jobs) == 1 and not result.complete and "detail_fetch_failed" in result.error


def test_oracle_nested_finder_and_detail():
    def handler(request):
        if request.url.path.endswith("Details"):
            return httpx.Response(200, json={"items": [{"ExternalDescriptionStr": "Full software work", "ExternalQualificationsStr": "Python"}]})
        assert "limit=100,offset=0" in request.url.params["finder"]
        assert request.url.params["expand"] == "requisitionList"
        return httpx.Response(200, json={"items": [{"TotalJobsCount": 1, "requisitionList": [{"Id": "90", "Title": "Intern", "PrimaryLocation": "Bengaluru", "PostedDate": "2026-10-01"}]}]})
    result = collect("oracle", handler, "https://acme.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2")
    assert result.complete and "Full software work" in result.jobs[0]["description"]
    assert result.jobs[0]["canonical_url"].endswith("/CX_2/job/90")


def test_eightfold_uses_position_id_for_details():
    def handler(request):
        if request.url.path.endswith("position_details"):
            assert request.url.params["position_id"] == "123"
            return httpx.Response(200, json={"data": {"jobDescription": "<p>Build Azure tooling</p>"}})
        return httpx.Response(200, json={"data": {"count": 1, "positions": [{"id": 123, "atsJobId": "REQ99", "name": "Intern", "positionUrl": "/careers/job/123", "locations": ["Hyderabad"]}]}})
    result = collect("eightfold", handler)
    assert result.complete and result.jobs[0]["requisition_id"] == "REQ99"
    assert result.jobs[0]["description"] == "Build Azure tooling"


def test_repeated_lever_page_stops_without_false_complete():
    data = [{"id": str(i), "text": "Intern", "description": "Build", "hostedUrl": f"https://jobs.lever.co/acme/{i}"} for i in range(100)]
    result = collect("lever", lambda r: httpx.Response(200, json=data))
    assert len(result.jobs) == 100 and not result.complete and "repeated" in result.error


def test_real_unstop_fixture_preserves_paid_stipend_and_skill_origin():
    payload = json.loads((FIXTURES / "unstop_record.json").read_text(encoding="utf-8"))
    x = payload["data"]["data"][0]
    assert x["isPaid"] is False
    parsed = parse_unstop(Source("unstop", "https://unstop.com/internships"), x)
    assert parsed["compensation"]["min"] == 12000
    assert parsed["compensation"]["max"] == 15000
    assert parsed["compensation"]["currency"] == "INR"
    assert parsed["work_mode"] == "remote" and len(parsed["description"]) > 500
    assert parsed["company_name"] == "Learntricks Edutech"
    assert parsed["company_domain"] is None
    assert parsed["evidence"][0]["skills_raw"]


def test_real_internshala_jsonld_retains_country_eligibility_separately():
    html = (FIXTURES / "internshala_jobposting.html").read_text(encoding="utf-8")
    items = parse_jsonld(Source("internshala", "https://internshala.com/internship/detail/example"), html)
    assert len(items) == 1
    x = items[0]
    assert x["external_id"] == "20263306820"
    assert x["work_mode"] == "remote" and "Delhi" in x["location"]
    assert x["evidence"][0]["applicant_location_requirements"]
    assert "Unpaid" in x["description"] and x["deadline"].startswith("2026-10-29")


def test_freehire_inferred_labels_are_not_authoritative():
    payload = json.loads((FIXTURES / "freehire_record.json").read_text(encoding="utf-8"))
    result = collect("freehire", lambda r: httpx.Response(200, json=payload))
    x = result.jobs[0]
    assert x["employment_type"] is None
    assert x["evidence"][0]["upstream_enrichment_is_inferred"] is True
    assert result.coverage_scope == "discovery" and result.complete
    assert "bounded_discovery_window" in result.metadata["warnings"][0]


def test_unrecognized_html_is_failure_not_zero():
    result = collect("generic", lambda r: httpx.Response(200, text="<html>Welcome to our careers platform</html>"))
    assert not result.complete and "no_public_jobposting_data" in result.error


def test_description_html_drops_scripts_forms_events_and_unsafe_links():
    html = safe_html('<p onclick="steal()">Hi</p><script>x</script><form><input value="x"></form><a href="javascript:steal()">link</a>')
    assert "script" not in html and "onclick" not in html and "input" not in html and "javascript" not in html
    assert "Hi" in html and "link" in html


def test_seed_registry_is_200_known_companies_not_200_fake_jobs():
    path = Path(__file__).parents[1] / "internshipos/data/company_seeds.json"
    seeds = json.loads(path.read_text(encoding="utf-8"))
    assert len(seeds) == len({x["domain"] for x in seeds}) == 200
    assert {"Microsoft", "Zoho", "Meesho", "Freshworks", "Tata Consultancy Services"} <= {x["name"] for x in seeds}
    assert all(x["verified"] and x["verification_status"] == "trusted_seed" for x in seeds)
    assert all(not s["verified"] and s["association_status"] == "candidate" for x in seeds for s in x["sources"])
    assert all(s["poll_interval_hours"] in {12, 24} for x in seeds for s in x["sources"])
    assert not any(x["domain"] in {"abc.com", "tellent.com", "fis-ski.com"} for x in seeds)


def test_openjobs_import_is_candidate_and_licensed():
    rows = import_openjobs({"greenhouse": ["acme", "bad/slug"]})
    assert len(rows) == 1 and rows[0]["verified"] is False
    assert rows[0]["provenance"]["license"] == "CC0-1.0"
    assert next(x for x in default_discovery_sources() if x["provider"] == "naukri")["enabled"] is False


def test_discovery_does_not_promote_unknown_company_identity():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='<a href="https://jobs.ashbyhq.com/acme">Careers</a>'))) as client:
            result = await discover_company("Acme", "acme.example.com", client=client, resolve_dns=False)
            assert result["verified"] is False and result["verification_status"] == "needs_review"
            assert result["sources"][0]["provider"] == "ashby"
            assert result["sources"][0]["config"]["association_evidence"]["linked_from"] == "https://acme.example.com"
    asyncio.run(run())


def test_verified_domain_plus_career_link_can_verify_association():
    async def run():
        def handler(request):
            if request.url.path == "/careers":
                return httpx.Response(200, text='<iframe src="https://job-boards.greenhouse.io/acme"></iframe>')
            return httpx.Response(200, text='<a href="/careers">Careers</a>')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await discover_company("Acme", "acme.example.com", trusted_domain=True, client=client, resolve_dns=False)
            assert result["sources"][0]["verified"] is True
            assert result["sources"][0]["config"]["association_evidence"]["linked_from"] == "https://acme.example.com/careers"
            assert result["discovery_status"] == "sources_found" and result["retry_after_hours"] == 720
    asyncio.run(run())


def test_supplied_ats_url_without_official_link_stays_candidate():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<h1>Acme</h1>"))) as client:
            result = await discover_company("Acme", "acme.example.com", "https://jobs.ashbyhq.com/other-company", trusted_domain=True, client=client, resolve_dns=False)
            assert result["sources"][0]["verified"] is False
            assert result["sources"][0]["config"]["association_evidence"]["kind"] == "supplied_url_only"
    asyncio.run(run())


def test_missing_domain_has_retry_state_instead_of_forever_first_in_queue():
    result = asyncio.run(discover_company("Unknown Employer"))
    assert result["discovery_status"] == "missing_domain"
    assert result["checked_at"] and result["retry_after_hours"] == 336
    assert result["verified"] is False


def test_saved_workday_refresh_fetches_path_without_inventory_scan():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"jobPostingInfo": {"title": "Saved Internship", "jobReqId": "JR9999", "jobDescription": "New full description", "location": "India", "endDate": "2026-11-01"}})
    result = collect("workday", handler, "https://acme.wd1.myworkdayjobs.com/External", config={
        "refresh_external_ids": ["JR9999"], "refresh_jobs": [{"external_id": "JR9999", "canonical_url": "https://acme.wd1.myworkdayjobs.com/External/job/India/Saved-Intern_JR9999", "opportunity_id": "OP1"}]})
    assert result.complete and result.coverage_scope == "targeted"
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path == "/wday/cxs/acme/External/job/India/Saved-Intern_JR9999"
    assert result.jobs[0]["deadline"] == "2026-11-01"


def test_saved_detail_404_is_uncertain_never_closed():
    result = collect("greenhouse", lambda r: httpx.Response(404), config={"refresh_external_ids": ["123"]})
    assert result.jobs == [] and not result.complete and result.coverage_scope == "targeted"
    assert "saved_detail_fetch_error" in result.error


def test_saved_refresh_from_single_feed_only_returns_requested_id():
    data = {"jobs": [{"id": "a", "title": "A", "descriptionPlain": "Full A", "jobUrl": "https://jobs.ashbyhq.com/acme/a"},
                     {"id": "b", "title": "B", "descriptionPlain": "Full B", "jobUrl": "https://jobs.ashbyhq.com/acme/b"}]}
    result = collect("ashby", lambda r: httpx.Response(200, json=data), config={"refresh_external_ids": ["b"]})
    assert result.complete and result.coverage_scope == "targeted"
    assert [x["external_id"] for x in result.jobs] == ["b"]


def test_oracle_snippet_is_not_full_detail_refresh():
    def handler(request):
        return httpx.Response(200, json={"items": [{"Title": "Intern", "ShortDescriptionStr": "Truncated search preview"}]})
    result = collect("oracle", handler, "https://acme.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1", config={"refresh_external_ids": ["123"]})
    assert not result.complete and result.jobs == []
    assert "full_description_missing" in result.error


def test_standard_compression_and_identity_fallback_are_explicit():
    attempts=[]
    def handle(request):
        attempts.append(request.headers['accept-encoding'])
        if len(attempts)==1:raise httpx.DecodingError('fixture invalid compressed response')
        return httpx.Response(200,json={'jobs':[]})
    result=collect('greenhouse',handle)
    assert result.complete and attempts==['gzip, deflate','identity']


def test_generic_detail_cursor_resumes_without_claiming_full_inventory():
    links='<a href="/jobs/one">One</a><a href="/jobs/two">Two</a>'
    def handle(request):
        if request.url.path=='/acme':return httpx.Response(200,text=links)
        return httpx.Response(200,text='<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Software Intern','identifier':request.url.path,'url':str(request.url),'description':'Build Python software','jobLocation':{'address':{'addressLocality':'Chennai','addressCountry':'India'}}})+'</script>')
    first=collect('generic',handle,max_details=1)
    second=collect('generic',handle,max_details=1,config={'detail_cursor':first.metadata['next_detail_cursor']})
    assert first.jobs[0]['external_id']!=second.jobs[0]['external_id']
    assert first.coverage_scope==second.coverage_scope=='discovery'
    assert second.metadata['next_detail_cursor']==0
